"""A free procedural stand-in for the world model, with ground truth.

It mirrors the LingBot World 2 contract (chunked generation, persistent actions, one chunk
of control latency) so the whole loop can be developed and tested without spending GPU
credits. It also knows the true clearance and time-to-contact, which lets us calibrate the
flow-based perception before trusting it inside a world model that has no ground truth.

Rendering is a vectorised 2.5D raycaster: textured pillars on a ground plane, with fog.
"""
import asyncio

import cv2
import numpy as np

from ..actions import EMBODIMENTS
from .base import Chunk, Scene, World

CHUNK_SECONDS = 0.25
SPEED = {"forward": 2.0, "back": 1.0, "strafe": 1.5, "yaw_deg": 60.0, "climb": 1.0}
PILLAR_HEIGHT = 5.0
DRONE_RADIUS = 0.3
ALT_RANGE = (0.4, 3.5)
CHASE_M, CHASE_UP_M = 1.6, 0.35  # third-person camera offset behind / above the drone

PALETTES = {
    "forest": dict(sky_top=(120, 170, 225), sky_bot=(215, 230, 245), ground=(78, 98, 52),
                   pillar=(105, 72, 46), fog=(205, 212, 220)),
    "warehouse": dict(sky_top=(52, 54, 60), sky_bot=(92, 94, 100), ground=(128, 126, 120),
                      pillar=(196, 118, 40), fog=(150, 150, 150)),
    "night": dict(sky_top=(8, 10, 20), sky_bot=(24, 26, 40), ground=(28, 32, 30),
                  pillar=(48, 40, 34), fog=(18, 18, 26)),
}


def _noise(rng, n=256, blur=3.0):
    tex = cv2.GaussianBlur(rng.normal(size=(n, n)).astype(np.float32), (0, 0), blur)
    tex = (tex - tex.mean()) / (tex.std() + 1e-6)
    return np.clip(1.0 + 0.22 * tex, 0.55, 1.45)


class MockWorld(World):
    kind = "mock"
    has_ground_truth = True

    def __init__(self, embodiment="drone", realtime=False, lag_chunks=1, frames_per_chunk=2,
                 size=(256, 144)):
        super().__init__(embodiment)
        self.realtime = realtime
        self.lag = lag_chunks
        self.fpc = frames_per_chunk
        self.W, self.H = size
        self.f = self.W / 2.0  # 90 degree horizontal FOV
        self.chunks = 0
        self.twin = None  # PhysicsTwin, set by the flight loop: then the physics moves the camera
        self.last_motion = None

    async def open(self, planned_seconds: float) -> None:
        return None

    async def start(self, scene: Scene):
        p = {"density": 6.0, "fog": 0.035, "palette": "forest", "radius": (0.25, 0.6), **scene.params}
        self.params = p
        self.rng = np.random.default_rng(scene.seed)
        self.tex_ground = _noise(self.rng, blur=2.0)
        self.tex_sky = _noise(self.rng, blur=6.0)
        area = 50.0
        n = int(p["density"] * area * area / 100.0)
        centres = self.rng.uniform(-area / 2, area / 2, size=(n * 2, 2))
        centres = centres[np.linalg.norm(centres, axis=1) > 3.0][:n]
        self.C = centres.astype(np.float32)
        self.R = self.rng.uniform(*p["radius"], size=len(self.C)).astype(np.float32)
        self.tint = self.rng.uniform(0.75, 1.2, size=(len(self.C), 1)).astype(np.float32)
        self.pos = np.zeros(2, np.float32)
        self.heading = float(self.rng.uniform(-np.pi, np.pi))
        self.alt = 1.2
        self.queue = ["hover"] * self.lag
        self.pending = "hover"
        self.index = 0
        self.odometer = 0.0
        self.collided = False
        self.sprite = self._make_sprite(scene.world_key)
        self.h0, self.p0 = self.heading, self.pos.copy()
        self.frame = self.render()
        return self.frame

    def _make_sprite(self, world_key):
        """Third-person worlds draw the same drone cutout the world-model seed uses, at the
        same place, so free runs exercise the masked perception and the Sentinel unchanged."""
        if not world_key:
            return None
        from ..config import ASSETS
        from ..prompts import WORLDS

        x, y, w, h = WORLDS[world_key].drone_box
        cut = cv2.imread(str(ASSETS / "seeds" / "drone_cutout.png"), cv2.IMREAD_UNCHANGED)
        sw, sh = int(w * self.W), int(h * self.H)
        cut = cv2.resize(cut, (sw, sh), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(cut[..., :3], cv2.COLOR_BGR2RGB).astype(np.float32)
        return rgb, cut[..., 3:].astype(np.float32) / 255.0, int(x * self.W), int(y * self.H)

    async def act(self, action: str) -> None:
        if action not in EMBODIMENTS[self.embodiment]:
            raise ValueError(f"{action} is not available to a {self.embodiment}")
        self.pending = action

    async def steer(self, prompt: str) -> None:
        text = prompt.lower()
        if any(k in text for k in ("fog", "smoke", "dust", "haze")):
            self.params["fog"] = 0.14
        if "clear" in text:
            self.params["fog"] = 0.02
        if any(k in text for k in ("night", "dark", "dusk", "lights fail", "dim")):
            self.params["palette"] = "night"
        if "day" in text:
            self.params["palette"] = "forest"
        if any(k in text for k in ("obstacle", "worker", "person", "falls", "crosses", "steps into", "forklift")):
            self._spawn_ahead()

    def _spawn_ahead(self, dist=4.5):  # far enough that a competent pilot can still stop or swerve
        d = np.array([np.cos(self.heading), np.sin(self.heading)], np.float32)
        side = np.array([-d[1], d[0]]) * self.rng.uniform(-0.3, 0.3)
        self.C = np.vstack([self.C, self.pos + d * dist + side]).astype(np.float32)
        self.R = np.append(self.R, 0.45).astype(np.float32)
        self.tint = np.vstack([self.tint, [[1.3]]]).astype(np.float32)

    async def next_chunk(self) -> Chunk:
        self.queue.append(self.pending)
        action = self.queue.pop(0)
        frames = []
        self._acc = [0.0, 0.0, 0.0, 0.0, 0.0]
        for _ in range(self.fpc):
            self._integrate(action, CHUNK_SECONDS / self.fpc)
        if self.twin is not None:
            from ..twin import Motion

            self.last_motion = Motion(*self._acc)
            frames.append(self.render())
        self.frame = frames[-1]
        info = self._truth()
        hires = cv2.resize(self.frame, (960, int(960 * self.H / self.W)), interpolation=cv2.INTER_LINEAR)
        chunk = Chunk(index=self.index, frames=frames, action=action, raw_action=action, info=info, hires=hires)
        self.index += 1
        self.chunks += 1
        # Always yield: an unpaced training run would otherwise starve the HTTP server.
        await asyncio.sleep(CHUNK_SECONDS if self.realtime else 0)
        return chunk

    async def close(self) -> None:
        return None

    def usage(self) -> dict:
        return {"backend": "mock", "chunks": self.chunks, "usd": 0.0}

    # ---- physics -------------------------------------------------------------------------
    def _integrate(self, action, dt):
        before = self.pos.copy()
        if self.twin is not None:
            m = self.twin.advance(action, dt)
            acc = self._acc
            self._acc = [acc[0] + m.forward_m, acc[1] + m.left_m, acc[2] + m.up_m, acc[3] + m.yaw_rad, acc[4] + m.seconds]
            q = self.twin.quad
            c, s = np.cos(self.h0), np.sin(self.h0)
            self.pos = (self.p0 + np.array([c * q.pos[0] - s * q.pos[1], s * q.pos[0] + c * q.pos[1]])).astype(np.float32)
            self.heading = self.h0 + q.yaw
            self.alt = float(np.clip(q.pos[2], *ALT_RANGE))
        else:
            self._move(action, dt)
        self.odometer += float(np.linalg.norm(self.pos - before))
        if self._clearance() < DRONE_RADIUS:
            self.collided = True

    def _move(self, action, dt):
        fwd = np.array([np.cos(self.heading), np.sin(self.heading)], np.float32)
        left = np.array([-fwd[1], fwd[0]], np.float32)
        if action in ("arc_left", "arc_right"):
            self.pos = self.pos + fwd * SPEED["forward"] * 0.75 * dt
            self.heading += np.radians(SPEED["yaw_deg"]) * dt * (1 if action == "arc_left" else -1)
        elif action == "forward":
            self.pos = self.pos + fwd * SPEED["forward"] * dt
        elif action == "back":
            self.pos = self.pos - fwd * SPEED["back"] * dt
        elif action == "left":
            self.pos = self.pos + left * SPEED["strafe"] * dt
        elif action == "right":
            self.pos = self.pos - left * SPEED["strafe"] * dt
        elif action == "yaw_left":
            self.heading += np.radians(SPEED["yaw_deg"]) * dt
        elif action == "yaw_right":
            self.heading -= np.radians(SPEED["yaw_deg"]) * dt
        elif action == "up":
            self.alt = min(ALT_RANGE[1], self.alt + SPEED["climb"] * dt)
        elif action == "down":
            self.alt = max(ALT_RANGE[0], self.alt - SPEED["climb"] * dt)

    def _clearance(self) -> float:
        if len(self.C) == 0:
            return float("inf")
        return float(np.min(np.linalg.norm(self.C - self.pos, axis=1) - self.R))

    def _ray(self, angles, origin=None):
        d = np.stack([np.cos(angles), np.sin(angles)], axis=1).astype(np.float32)
        rel = self.C - (self.pos if origin is None else origin)
        b = d @ rel.T
        c = (rel ** 2).sum(1) - self.R ** 2
        disc = b ** 2 - c[None, :]
        root = np.sqrt(np.maximum(disc, 0))
        t = np.where(c[None, :] < 0, b + root, b - root)
        t = np.where((disc > 0) & (t > 0.01), t, np.inf)
        idx = np.argmin(t, axis=1)
        return d, t[np.arange(len(angles)), idx], idx

    def _truth(self) -> dict:
        _, t, _ = self._ray(np.array([self.heading], np.float32))
        surface = float(t[0])
        forward_m_per_chunk = SPEED["forward"] * CHUNK_SECONDS
        return {
            "collided": self.collided,
            "clearance_m": round(self._clearance(), 3),
            "ahead_m": round(surface, 3) if np.isfinite(surface) else None,
            "ttc_chunks": round((surface - DRONE_RADIUS) / forward_m_per_chunk, 2) if np.isfinite(surface) else None,
            "pos": [round(float(self.pos[0]), 2), round(float(self.pos[1]), 2)],
            "heading_deg": round(float(np.degrees(self.heading)) % 360, 1),
            "alt_m": round(self.alt, 2),
            "odometer_m": round(self.odometer, 2),
        }

    # ---- rendering -----------------------------------------------------------------------
    def render(self) -> np.ndarray:
        W, H, f = self.W, self.H, self.f
        pal = PALETTES[self.params["palette"]]
        fog_k = self.params["fog"]
        horizon = H / 2.0
        off = np.arctan((np.arange(W) + 0.5 - W / 2.0) / f).astype(np.float32)
        angles = self.heading - off
        # Third person: a chase camera behind and above the drone, like the world-model view,
        # so obstacles show up around the drone before it reaches them.
        chase = getattr(self, "sprite", None) is not None
        fwd = np.array([np.cos(self.heading), np.sin(self.heading)], np.float32)
        cam = self.pos - fwd * CHASE_M if chase else self.pos
        cam_alt = self.alt + CHASE_UP_M if chase else self.alt
        d, t_hit, idx = self._ray(angles, cam)
        perp = t_hit * np.cos(off)

        rows = (np.arange(H, dtype=np.float32) + 0.5)[:, None]
        img = np.empty((H, W, 3), np.float32)

        # Sky (or warehouse ceiling): vertical gradient with a texture that moves with yaw.
        elev = np.clip((horizon - rows) / horizon, 0, 1)
        sky = (1 - elev)[..., None] * np.array(pal["sky_bot"], np.float32) + elev[..., None] * np.array(pal["sky_top"], np.float32)
        tu = np.floor(angles[None, :] * 80.0).astype(np.int64) % 256
        tv = np.floor((horizon - rows) * 2.0).astype(np.int64) % 256
        sky = sky * (0.85 + 0.15 * self.tex_sky[tv, tu])[..., None]
        img[:] = sky

        # Ground plane via floor casting.
        below = rows[:, 0] > horizon
        r = rows[below]
        dist = (f * cam_alt / (r - horizon)) / np.cos(off)[None, :]
        gx = cam[0] + d[None, :, 0] * dist
        gy = cam[1] + d[None, :, 1] * dist
        tex = self.tex_ground[np.floor(gy * 24).astype(np.int64) % 256, np.floor(gx * 24).astype(np.int64) % 256]
        checker = ((np.floor(gx) + np.floor(gy)) % 2) * 0.12 + 0.94
        ground = np.array(pal["ground"], np.float32) * (tex * checker)[..., None]
        fog = np.exp(-fog_k * dist)[..., None]
        img[below] = ground * fog + np.array(pal["fog"], np.float32) * (1 - fog)

        # Pillars.
        finite = np.isfinite(perp)
        safe = np.where(finite, perp, 1.0)
        y_bot = horizon + f * cam_alt / safe
        y_top = horizon - f * (PILLAR_HEIGHT - cam_alt) / safe
        mask = (rows >= y_top[None, :]) & (rows <= y_bot[None, :]) & finite[None, :]
        if mask.any():
            hit = cam + d * np.where(finite, t_hit, 0)[:, None]
            phi = np.arctan2(hit[:, 1] - self.C[idx, 1], hit[:, 0] - self.C[idx, 0])
            stripe = 0.8 + 0.2 * np.sign(np.sin(phi * 9.0))
            z = cam_alt + (horizon - rows) * safe[None, :] / f
            band = 0.88 + 0.12 * np.sign(np.sin(z * 4.0))
            shade = (stripe[None, :] * band * self.tint[idx, 0][None, :])
            col = np.array(pal["pillar"], np.float32) * shade[..., None]
            fogp = np.exp(-fog_k * np.where(finite, t_hit, 1e3))[None, :, None]
            col = col * fogp + np.array(pal["fog"], np.float32) * (1 - fogp)
            img[mask] = col[mask]
        if getattr(self, "sprite", None) is not None:
            rgb, a, sx, sy = self.sprite
            region = img[sy:sy + rgb.shape[0], sx:sx + rgb.shape[1]]
            img[sy:sy + rgb.shape[0], sx:sx + rgb.shape[1]] = region * (1 - a) + rgb * a
        return np.clip(img, 0, 255).astype(np.uint8)
