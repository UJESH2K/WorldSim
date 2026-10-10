"""Training ground: the practice world + quadrotor physics + ground truth, stepped synchronously.

One step = one 0.25 s decision. The world renders a third-person chase view of the drone (as in
the product), the physics twin moves it, and the ground truth (obstacle positions) feeds the
reward, the collision check and the privileged expert. Built to run many copies in parallel.
"""
import asyncio

import cv2
import numpy as np

from ..twin import PhysicsTwin
from ..worlds.base import Scene
from ..worlds.mock import MockWorld
from .expert import Expert
from .pilot import gray, observe

MAX_STEPS = 40  # 10 s
NEAR = 0.6  # m of clearance that counts as a near miss
PALETTES = ["forest", "warehouse", "night"]


def scenarios(n: int, seed: int, events: bool = True, profile: str = "field") -> list[dict]:
    """A reproducible set of situations.

    field:      where the pilot has to work. Two places, three looks (day, warehouse, night),
                dense clutter, and in half the flights someone steps into the path.
    open-field: what a stock pilot is trained on. Daylight forest, sparse, nothing moves.
    """
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        if profile == "open-field":
            sc = {"world": "forest", "palette": "forest", "density": float(rng.uniform(2.5, 4.5)), "event_at": None}
        else:
            sc = {"world": ["forest", "warehouse"][i % 2], "palette": PALETTES[i % 3],
                  "density": float(rng.uniform(4.5, 8.0)),
                  "event_at": int(rng.integers(8, 24)) if (events and rng.random() < 0.5) else None}
        out.append({"id": f"s{seed}-{i:02d}", "seed": int(rng.integers(0, 1_000_000)), "profile": profile, **sc})
    return out


class LabEnv:
    def __init__(self, scenario: dict, size=(192, 108), hz: int = 200):
        self.sc = scenario
        self.world = MockWorld("drone", realtime=False, size=size, frames_per_chunk=1)
        self.twin = PhysicsTwin(hz=hz, engine="builtin")
        self.world.twin = self.twin
        self.expert = Expert(self.twin.profile)
        self.loop = asyncio.new_event_loop()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def reset(self):
        sc = self.sc
        scene = Scene(name=sc["id"], prompt="", seed=sc["seed"], world_key=sc["world"],
                      params={"palette": sc["palette"], "density": sc["density"]})
        first = self._run(self.world.start(scene))
        self.k = 0
        self.cur = observe(first)
        self.prev = gray(self.cur)
        self.frame = first
        self.dist0 = self.twin.distance_m
        return self.obs()

    def obs(self):
        active = self.world.queue[0] if self.world.queue else self.world.pending
        return self.prev, self.cur, active

    def expert_action(self) -> str:
        w = self.world
        active = w.queue[0] if w.queue else w.pending
        speed = float(self.twin.quad.body_velocity()[0])
        return self.expert.choose(w.pos, w.heading, speed, active, w.C, w.R)[0]

    def step(self, action: str):
        if self.sc.get("event_at") == self.k:
            self._run(self.world.steer("a worker steps into the path"))
        self._run(self.world.act(action))
        before = self.twin.distance_m
        chunk = self._run(self.world.next_chunk())
        self.k += 1
        self.frame = chunk.frames[-1]
        self.prev, self.cur = gray(self.cur), observe(self.frame)
        clear = float(chunk.info["clearance_m"])
        collided = bool(chunk.info["collided"])
        progress = self.twin.distance_m - before
        reward = progress - (1.5 if clear < NEAR else 0.0) - (20.0 if collided else 0.0)
        done = collided or self.k >= MAX_STEPS
        return self.obs(), reward, done, {"clearance": clear, "collided": collided, "progress": progress,
                                          "distance": self.twin.distance_m - self.dist0}

    def thumb(self, width=320) -> np.ndarray:
        h = int(width * self.frame.shape[0] / self.frame.shape[1])
        return cv2.resize(self.frame, (width, h), interpolation=cv2.INTER_LINEAR)
