"""Free practice world built from the user's own photo.

The view is a virtual camera over the photo: forward zooms in, back zooms out, turning and
sliding pan across it (the photo is mirror-extended at the edges), climbing tilts. It does not
invent anything beyond the photo; the real AI world (LingBot) does that. It exists so a venue
photo can be flown for free, with the same drone, Sentinel and autopilot as the real thing.
"""
import asyncio

import cv2
import numpy as np

from ..actions import EMBODIMENTS
from ..config import ASSETS
from ..prompts import WORLDS
from .base import Chunk, Scene, World

CHUNK_SECONDS = 0.25
SUBSTEPS = 6  # frames per chunk: ~24 fps on screen
OUT = (960, 554)
SMALL = (416, 240)
ZOOM_RANGE = (1.0, 3.2)
RATE = {"zoom": 0.45, "yaw": 0.22, "strafe": 0.12, "climb": 0.10}  # per second


class PhotoWorld(World):
    kind = "photo"
    has_ground_truth = False

    def __init__(self, embodiment="drone", realtime=True):
        super().__init__(embodiment)
        self.realtime = realtime
        self.on_display = None
        self.twin = None  # PhysicsTwin, set by the flight loop
        self.last_motion = None
        self.index = 0
        self.chunks = 0

    async def open(self, planned_seconds: float) -> None:
        return None

    async def start(self, scene: Scene):
        spec = WORLDS[scene.world_key]
        photo = cv2.imread(str(ASSETS / "seeds" / spec.image.replace("_drone.jpg", ".jpg")))
        if photo is None:
            raise FileNotFoundError(f"no photo for {scene.world_key}")
        self.h, self.w = photo.shape[:2]
        # Mirror-extend so turning can pan past the edges without black borders.
        self.pad_x, self.pad_y = self.w, self.h // 2
        self.canvas = cv2.copyMakeBorder(photo, self.pad_y, self.pad_y, self.pad_x, self.pad_x, cv2.BORDER_REFLECT)
        self.canvas = cv2.cvtColor(self.canvas, cv2.COLOR_BGR2RGB)
        self.cx, self.cy, self.zoom = self.pad_x + self.w / 2, self.pad_y + self.h / 2, 1.0
        self.dim = 1.0
        cut = cv2.imread(str(ASSETS / "seeds" / "drone_cutout.png"), cv2.IMREAD_UNCHANGED)
        x, y, bw, bh = spec.drone_box
        sw, sh = int(bw * OUT[0]), int(bh * OUT[1])
        cut = cv2.resize(cut, (sw, sh), interpolation=cv2.INTER_AREA)
        self.sprite = (cv2.cvtColor(cut[..., :3], cv2.COLOR_BGR2RGB).astype(np.float32),
                       cut[..., 3:].astype(np.float32) / 255.0, int(x * OUT[0]), int(y * OUT[1]))
        self.pending, self.queue, self.index = "hover", ["hover"], 0
        self.edge = False
        return self.render()

    async def act(self, action: str) -> None:
        if action not in EMBODIMENTS[self.embodiment]:
            raise ValueError(f"{action} is not available to a {self.embodiment}")
        self.pending = action

    async def steer(self, prompt: str) -> None:
        # Only lighting can be shown on a still photo; people and objects need the real AI world.
        if any(k in prompt.lower() for k in ("dim", "dark", "dusk", "lights fail")):
            self.dim = 0.45

    def _move(self, action: str, dt: float):
        if self.twin is not None:
            return self._move_physical(action, dt)
        z0 = self.zoom
        if action in ("forward", "arc_left", "arc_right"):
            self.zoom *= 1 + RATE["zoom"] * dt * (0.75 if action != "forward" else 1)
        elif action == "back":
            self.zoom /= 1 + RATE["zoom"] * dt
        span = self.w / self.zoom
        if action in ("yaw_left", "arc_left"):
            self.cx -= RATE["yaw"] * self.w * dt
        elif action in ("yaw_right", "arc_right"):
            self.cx += RATE["yaw"] * self.w * dt
        elif action == "left":
            self.cx -= RATE["strafe"] * self.w * dt
        elif action == "right":
            self.cx += RATE["strafe"] * self.w * dt
        elif action == "up":
            self.cy -= RATE["climb"] * self.h * dt
        elif action == "down":
            self.cy += RATE["climb"] * self.h * dt
        self.zoom = float(np.clip(self.zoom, *ZOOM_RANGE))
        self.edge = action == "forward" and self.zoom == ZOOM_RANGE[1] and z0 == self.zoom
        # Stay inside the extended canvas.
        half_w, half_h = span / 2, self.h / self.zoom / 2
        self.cx = float(np.clip(self.cx, half_w, self.canvas.shape[1] - half_w))
        self.cy = float(np.clip(self.cy, half_h, self.canvas.shape[0] - half_h))

    DEPTH_M = 5.0  # assumed distance to the scene: sets how fast forward travel zooms in

    def _move_physical(self, action: str, dt: float):
        """Apply the physics' motion as a camera move with a fixed 90 degree lens."""
        m = self.twin.advance(action, dt)
        acc = self._acc
        self._acc = [acc[0] + m.forward_m, acc[1] + m.left_m, acc[2] + m.up_m, acc[3] + m.yaw_rad, acc[4] + m.seconds]
        z0 = self.zoom
        self.zoom = float(np.clip(self.zoom * np.exp(m.forward_m / self.DEPTH_M), *ZOOM_RANGE))
        f_px = self.w / 2 / self.zoom  # canvas pixels per unit tan(angle) at this zoom
        self.cx -= np.tan(m.yaw_rad) * f_px + m.left_m / self.DEPTH_M * f_px
        self.cy -= m.up_m / self.DEPTH_M * f_px
        self.edge = m.forward_m > 0.005 and self.zoom == ZOOM_RANGE[1] and z0 == self.zoom
        half_w, half_h = self.w / self.zoom / 2, self.h / self.zoom / 2
        self.cx = float(np.clip(self.cx, half_w, self.canvas.shape[1] - half_w))
        self.cy = float(np.clip(self.cy, half_h, self.canvas.shape[0] - half_h))

    def render(self) -> np.ndarray:
        bw, bh = self.w / self.zoom, self.h / self.zoom
        x0, y0 = int(self.cx - bw / 2), int(self.cy - bh / 2)
        view = self.canvas[y0:y0 + int(bh), x0:x0 + int(bw)]
        img = cv2.resize(view, OUT, interpolation=cv2.INTER_LINEAR).astype(np.float32) * self.dim
        rgb, a, sx, sy = self.sprite
        region = img[sy:sy + rgb.shape[0], sx:sx + rgb.shape[1]]
        img[sy:sy + rgb.shape[0], sx:sx + rgb.shape[1]] = region * (1 - a) + rgb * a
        return np.clip(img, 0, 255).astype(np.uint8)

    async def next_chunk(self) -> Chunk:
        self.queue.append(self.pending)
        action = self.queue.pop(0)  # one chunk of control latency, like the real model
        frames = []
        self._acc = [0.0, 0.0, 0.0, 0.0, 0.0]
        for _ in range(SUBSTEPS):
            self._move(action, CHUNK_SECONDS / SUBSTEPS)
            frame = self.render()
            frames.append(frame)
            if self.on_display:
                self.on_display(frame)
            await asyncio.sleep(CHUNK_SECONDS / SUBSTEPS if self.realtime else 0)
        if self.twin is not None:
            from ..twin import Motion

            self.last_motion = Motion(*self._acc)
        hires = frames[-1]
        keep = [cv2.resize(f, SMALL, interpolation=cv2.INTER_AREA) for f in (frames[0], frames[len(frames) // 2], frames[-1])]
        chunk = Chunk(index=self.index, frames=keep, action=action, raw_action=action,
                      info={"zoom": round(self.zoom, 2), "edge_of_photo": self.edge}, hires=hires)
        self.index += 1
        self.chunks += 1
        return chunk

    async def close(self) -> None:
        return None

    def usage(self) -> dict:
        return {"backend": "photo", "chunks": self.chunks, "usd": 0.0}
