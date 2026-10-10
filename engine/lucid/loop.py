"""The closed loop: observe a chunk, perceive, label, act, and record every step.

    world.next_chunk() -> frames + the action that actually generated them
    perceive()         -> flow ego-motion, looming danger, obedience of that chunk
    teacher.label()    -> what the expert would do from here
    controller         -> teacher, student, or a beta-mix of the two (DAgger)
    world.act()        -> lands one chunk later (world-model control latency)
"""
import shutil
import time
from collections import deque

import cv2
import numpy as np

from . import budget
from .bank import EpisodeRecorder
from .perception import Perception, perceive, prep
from .worlds.base import Scene, World


class Telemetry:
    """Live state for the dashboard. Written by the loop, read by the HTTP server."""

    def __init__(self):
        self.status = "idle"
        self.detail = ""
        self.config = {}
        self.jpeg = None
        self.last = {}
        self.steps = deque(maxlen=400)
        self.rounds = []
        self.episodes = deque(maxlen=200)
        self.log = deque(maxlen=200)
        self.usage = {}
        self.stop_requested = False
        self.steer_queue = []

    def say(self, msg: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')}  {msg}")
        print(msg, flush=True)

    def frame(self, rgb: np.ndarray) -> None:
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
        if ok:
            self.jpeg = buf.tobytes()

    def snapshot(self) -> dict:
        return {
            "status": self.status, "detail": self.detail, "config": self.config, "last": self.last,
            "steps": list(self.steps)[-120:], "rounds": self.rounds, "episodes": list(self.episodes)[-50:],
            "log": list(self.log)[-60:], "usage": self.usage,
        }


async def run_episode(world: World, scene: Scene, teacher, *, student=None, beta: float = 1.0,
                      max_chunks: int = 40, rng=None, recorder: EpisodeRecorder | None = None,
                      telemetry: Telemetry | None = None, samples: list | None = None,
                      obedience_min: float = 0.3) -> dict:
    """Drive one episode. `beta` is the probability of executing the teacher's action."""
    rng = rng or np.random.default_rng()
    left, need = world.time_left(), world.episode_seconds(max_chunks)
    if left is not None and left < need:
        # Starting anyway would pay for a partial episode that Reactor then cuts off.
        if recorder:
            shutil.rmtree(recorder.dir, ignore_errors=True)
        raise budget.BudgetExceeded(f"{left:.0f}s of session left, an episode needs ~{need:.0f}s: stopping cleanly")
    first = await world.start(scene)
    prev = prep(first) if first is not None else None
    events = {e["at"]: e["prompt"] for e in scene.events}
    stats = {"scene": scene.name, "chunks": 0, "collided": False if world.has_ground_truth else None, "teacher_steps": 0, "agree": 0,
             "labelled": 0, "rejected": 0, "danger_max": 0.0, "obedience_sum": 0.0, "events": 0}
    t0 = time.perf_counter()

    for k in range(max_chunks):
        if telemetry and telemetry.stop_requested:
            break
        if k in events:
            await world.steer(events[k])
            stats["events"] += 1
            if telemetry:
                telemetry.say(f"event @chunk {k}: {events[k][-70:]}")
        if telemetry and telemetry.steer_queue:
            # A live event is added to the scene, not a replacement for it: LingBot needs the
            # prompt to keep describing what the seed image shows, or the world drifts.
            prompt = telemetry.steer_queue.pop(0)
            await world.steer(f"{scene.prompt} {prompt}")
            telemetry.say(f"live steer: {prompt[:80]}")

        chunk = await world.next_chunk()
        cur = prep(chunk.frames[-1])
        if prev is None and len(chunk.frames) > 1:
            prev = prep(chunk.frames[0])
        p: Perception | None = perceive(prev, cur, chunk.action) if prev is not None else None
        label, reason = teacher.label(p, chunk.action)

        if student is not None and student.trained and prev is not None and rng.random() >= beta:
            action, probs = student.act(prev, cur, chunk.action)
            controller = "student"
        else:
            action, probs, controller = label, None, "teacher"
        await world.act(action)

        obey = p.obedience if p else None
        step = {
            "chunk": chunk.index, "active": chunk.action, "raw_active": chunk.raw_action,
            "label": label, "reason": reason, "action": action, "controller": controller,
            "probs": probs, "perception": p.to_dict() if p else None, "truth": chunk.info,
            "t": round(time.perf_counter() - t0, 3),
        }
        if samples is not None and prev is not None and p is not None:
            if obey is not None and obey < obedience_min and chunk.action != "hover":
                stats["rejected"] += 1  # the world ignored the control: not a valid training state
            else:
                samples.append((prev, cur, chunk.action, label))
                stats["labelled"] += 1

        stats["chunks"] += 1
        stats["teacher_steps"] += controller == "teacher"
        stats["agree"] += action == label
        stats["obedience_sum"] += obey or 0.0
        stats["danger_max"] = max(stats["danger_max"], p.danger if p else 0.0)
        if recorder:
            recorder.add(step, cur, chunk.frames[-1])
        if telemetry:
            telemetry.last = step
            telemetry.steps.append({k2: step[k2] for k2 in ("chunk", "active", "label", "action", "controller")}
                                   | {"danger": p.danger if p else 0, "obedience": obey, "truth": chunk.info})
            telemetry.frame(chunk.frames[-1])
            telemetry.usage = world.usage()
        prev = cur
        stats["distance_m"] = chunk.info.get("odometer_m")
        if chunk.info.get("collided"):
            stats["collided"] = True
            break

    n = max(1, stats["chunks"])
    summary = {**stats, "agreement": round(stats["agree"] / n, 3),
               "obedience_mean": round(stats["obedience_sum"] / n, 3),
               "seconds": round(time.perf_counter() - t0, 2)}
    del summary["agree"], summary["obedience_sum"]
    if recorder:
        recorder.close(summary)
    return summary
