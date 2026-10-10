"""Live flight: a third-person drone, a human or an autopilot at the controls, and the
Sentinel calling every step.

    each chunk (~0.5 s on LingBot World 2):
      perceive   flow around the masked drone -> looming, lateral balance, obedience
      assess     Sentinel -> clear | caution | warning | collision | anomaly, with reasons
      decide     human keys if held, else the autopilot (Sentinel overrides the reflex)
      act        lands ~2 chunks later (world-model latency)

Auto-tune runs the same loop over a grid of autopilot settings and keeps the one that
covers the most ground for the fewest Sentinel calls: tuning a controller against the
generated world before it ever flies a real one.
"""
import asyncio
import base64
import json
import time
from collections import deque
from dataclasses import asdict, dataclass

import cv2
import numpy as np

from .audit import WorldAudit
from .bank import EpisodeRecorder
from .lab.pilot import gray as lab_gray
from .lab.pilot import observe as lab_observe
from .config import DATA
from .perception import perceive, prep
from .prompts import WORLDS
from .sentinel import SEVERITY, Assessment, Narrator, Sentinel
from .teacher import ReflexTeacher
from .twin import Calibrator, PhysicsTwin, build_report
from .worlds.base import Scene, World

PILOT_FILE = DATA / "pilot.json"


@dataclass
class PilotParams:
    veer: float = 0.2  # looming that makes the reflex arc away
    spin: float = 0.45  # looming that makes it turn on the spot
    balance: float = 0.3  # lateral flow imbalance that makes it re-centre
    yield_gap: float = 0.75  # stop for a person/vehicle closer than this (drone-widths)

    @classmethod
    def load(cls, kind: str = "mock") -> "PilotParams":
        """The auto-tuned settings for this world kind, else its defaults. LingBot's masked
        looming runs higher in clear flight, so its reflex thresholds start higher."""
        if PILOT_FILE.exists():
            saved = json.loads(PILOT_FILE.read_text(encoding="utf-8"))
            if kind in saved:
                return cls(**saved[kind]["params"])
        return cls(veer=0.45, spin=0.7) if kind == "reactor" else cls()


class Autopilot:
    """The flow reflex, with the Sentinel's verdict taking precedence."""

    def __init__(self, params: PilotParams, embodiment: str = "drone"):
        self.params = params
        self.reflex = ReflexTeacher(embodiment, veer=params.veer, spin=params.spin, balance=params.balance)

    def decide(self, p, active: str, a: Assessment) -> tuple[str, str]:
        if a.verdict == "anomaly":
            return "hover", "holding: the world model stopped being trustworthy"
        touching = [h for h in a.hazards if h.zone == "touching"]
        if touching:
            # Brake, never reverse: in a chase view, flying back brings the drone into the
            # camera and breaks the third-person framing (seen on LingBot's warehouse).
            return "hover", f"braking: {touching[0].label} at the drone"
        near = [h for h in a.hazards if h.label in ("person", "vehicle") and h.gap < self.params.yield_gap]
        if near:
            h = min(near, key=lambda h: h.gap)
            cx = (h.box[0] + h.box[2]) / 2
            if h.zone == "ahead" or abs(cx - 0.5) < 0.08:
                return "hover", f"yielding to the {h.label} ahead"
            return ("arc_left" if cx > 0.5 else "arc_right"), f"giving the {h.label} room"
        if a.danger > 0.75:
            return "hover", f"braking: impact imminent (looming {a.danger:.2f})"
        return self.reflex.label(p, active)


class FlightState:
    """Everything the dashboard shows about a flight. Written by the loop, read over HTTP."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.world = None
        self.scene = None
        self.autopilot = True
        self.manual: str | None = None  # action from held keys; None = hands off
        self.events: list[str] = []
        self.decisions = deque(maxlen=600)
        self.alerts = deque(maxlen=40)  # warnings and worse, with a thumbnail
        self.counts = {"decisions": 0, "autopilot": 0, "human": 0, "caution": 0, "warning": 0,
                       "collision": 0, "anomaly": 0}
        self.assessment: dict = {}
        self.narration = None
        self.last_reason = ""
        self.tune: list[dict] = []
        self.params = asdict(PilotParams.load("mock"))
        self.physics: dict = {}  # live quadrotor state from the physics twin
        self.calibration: dict = {}  # render-vs-physics weights, this flight and saved
        self.report_id: str | None = None
        self.audit: dict | None = None  # world-model audit (LingBot flights): drift, morphs, pop-ins, re-anchors
        self.brain = getattr(self, "brain", "reflex")  # autopilot: "reflex" (hand-tuned) | "learned" (a Pilot Lab network)
        self.learned = getattr(self, "learned", None)  # (name, lucid.lab.pilot.Pilot) when one is loaded

    def snapshot(self) -> dict:
        return {"world": self.world, "scene": self.scene, "autopilot": self.autopilot, "manual": self.manual,
                "decisions": list(self.decisions)[-240:], "alerts": list(self.alerts)[-12:],
                "counts": self.counts, "assessment": self.assessment, "narration": self.narration,
                "tune": self.tune, "params": self.params, "physics": self.physics,
                "calibration": self.calibration, "report_id": self.report_id, "audit": self.audit,
                "brain": self.brain, "brain_name": self.learned[0] if self.learned else None}


def _thumb(rgb: np.ndarray) -> str:
    small = cv2.resize(rgb, (320, int(320 * rgb.shape[0] / rgb.shape[1])), interpolation=cv2.INTER_AREA)
    return base64.b64encode(cv2.imencode(".jpg", cv2.cvtColor(small, cv2.COLOR_RGB2BGR),
                                         [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes()).decode()


async def fly(world: World, scene_key: str, flight: FlightState, telemetry, *, params: PilotParams | None = None,
              max_chunks: int | None = None, seed: int = 0, record: bool = True, narrate: bool = True,
              sentinel: Sentinel | None = None, run_id: str | None = None,
              narrator: Narrator | None = None) -> dict:
    """Fly until stopped, out of session time, or `max_chunks`. Returns a score summary."""
    spec = WORLDS[scene_key]
    params = params or PilotParams.load(world.kind)
    pilot = Autopilot(params, world.embodiment)
    # Built off the event loop: it may have to wait for the detector to finish loading.
    sentinel = sentinel or await asyncio.to_thread(Sentinel, spec, kind=world.kind)
    sentinel.reset()
    # Only a generative world can drift, morph its drone or invent obstacles: audit those.
    audit = await asyncio.to_thread(WorldAudit, spec) if world.kind == "reactor" and record else None
    flight.audit = None
    narrator = (narrator or Narrator("qwen2.5vl:3b")) if narrate else None
    scene = Scene(name=scene_key, prompt="", seed=seed, params=dict(spec.mock), world_key=scene_key)
    rec = EpisodeRecorder(run_id or time.strftime("flight-%Y%m%d-%H%M%S"), 0, scene_key, world.kind) if record else None

    left = world.time_left()
    if max_chunks and left is not None and left < world.episode_seconds(max_chunks):
        from .budget import BudgetExceeded

        raise BudgetExceeded(f"{left:.0f}s of session left, a {max_chunks}-chunk flight needs "
                             f"~{world.episode_seconds(max_chunks):.0f}s: stopping cleanly")
    # Physics is the source of truth for the drone; worlds that can (mock, photo) are moved by it,
    # LingBot is driven to match it and checked against it by the calibrator.
    twin = PhysicsTwin()
    world.twin = twin
    calib = Calibrator(world.kind)
    if world.kind == "reactor":
        # LingBot's turn speed is in degrees per latent frame (3 per ~0.5 s chunk); match the
        # physical yaw rate, corrected by the learned render weight.
        deg = twin.profile.yaw_rate_dps * 0.5 / 3 / max(0.2, calib.k_yaw)
        await world.set_rotation_speed(float(np.clip(deg, 0.5, 30.0)))
    flight.calibration = {"k_yaw_saved": calib.k_yaw, "flights_calibrated": len(calib.saved.get("history", []))}
    first = await world.start(scene)
    prev = prep(first) if first is not None else None
    score = {"chunks": 0, "forward": 0, "warning": 0, "collision": 0, "anomaly": 0, "crashed_truth": False}
    t0 = time.perf_counter()
    try:
        await _loop(world, spec, flight, telemetry, pilot, sentinel, narrator, rec, prev, score, t0, max_chunks, scene,
                    twin, calib, audit)
    finally:
        if rec:
            rec.close(score)
            calibration = calib.commit()
            if audit is not None:
                rec.save_audit(audit.snapshot(events=200) | {"readings": [r.to_dict() for r in audit.readings]})
            report = build_report(rec.dir.parent.name, {"key": scene_key, "title": spec.title}, world.kind, twin,
                                  list(flight.decisions), calibration, asdict(params),
                                  audit.snapshot(events=60) if audit is not None else None)
            flight.calibration, flight.report_id = calibration, report["id"]
            telemetry.say(f"flight report {report['id']}: {report['verdict']} "
                          f"({report['metrics']['distance_m']} m, battery {report['metrics']['battery_end_pct']}%)")
    score["seconds"] = round(time.perf_counter() - t0, 1)
    score["distance_m"] = round(twin.distance_m, 2)  # physical distance, from the simulation
    score["energy_wh"] = round(twin.quad.energy_wh, 4)
    return score


async def _loop(world, spec, flight, telemetry, pilot, sentinel, narrator, rec, prev, score, t0, max_chunks, scene,
                twin, calib, audit=None):
    k = 0
    t_last = time.perf_counter()
    audit_job = None
    lab_view = None
    respawn = max_chunks is None  # live flights carry on after a crash; scored flights end on it
    while not telemetry.stop_requested and (max_chunks is None or k < max_chunks):
        while flight.events:
            label = flight.events.pop(0)
            await world.steer(label)
            telemetry.say(f"event: {label}")
            if audit is not None:
                audit.expect_change(k + 1)  # asked-for obstacles are not hallucinations
        chunk = await world.next_chunk()
        k += 1
        # Physics for this chunk: worlds moved by the twin report the motion they applied; for
        # LingBot the twin flies what the world actually executed, for as long as it took.
        now = time.perf_counter()
        motion = getattr(world, "last_motion", None)
        if motion is None:
            motion = twin.advance(chunk.action, float(np.clip(now - t_last, 0.2, 1.0)))
        t_last = now
        rgb = chunk.frames[-1]
        hires = chunk.hires if chunk.hires is not None else rgb
        lp_prev = lab_gray(lab_view) if lab_view is not None else None
        lab_view = lab_observe(rgb)  # what a learned pilot sees
        cur = prep(rgb)
        if prev is None and len(chunk.frames) > 1:
            prev = prep(chunk.frames[0])
        p = perceive(prev, cur, chunk.action, mask=spec.flow_mask) if prev is not None else None
        calib.observe(motion, p)
        flight.physics = twin.telemetry()
        # A still photo ends: flying "forward" past it is not the world ignoring the controls.
        edge = bool(chunk.info.get("edge_of_photo"))
        a = sentinel.assess(hires, p, "hover" if edge else chunk.action)  # the narrator never votes
        if edge:
            a.reasons.insert(0, "end of your photo: the free preview cannot fly further")
            if a.verdict == "clear":
                a.verdict = "caution"
        if audit is not None:
            # Off the control path (~130 ms of CNN per chunk): read last chunk's result, start this one.
            if audit_job is not None and audit_job.done():
                for e in audit_job.result().events:
                    telemetry.say(f"world audit, chunk {e.chunk}: {e.kind} ({e.detail})")
                audit_job = None
                if audit.should_reanchor() and hasattr(world, "reanchor"):
                    k_from, frame = audit.last_trusted
                    telemetry.say(f"world audit: the world failed its checks for 4 chunks in a row; "
                                  f"restarting LingBot from chunk {k_from}, the last frame it trusted")
                    await world.reanchor(frame, scene.seed)
                    audit.reanchored(chunk.index)
                flight.audit = audit.snapshot()
            if audit_job is None:
                audit_job = asyncio.create_task(asyncio.to_thread(
                    audit.update, hires, chunk.index, [(h.raw, h.conf, h.box) for h in a.hazards]))

        if flight.manual:
            action, by, why = flight.manual, "human", "keys"
        elif flight.autopilot and edge:
            action, by, why = "back", "autopilot", "end of the photo: backing out to explore"
        elif flight.autopilot and flight.brain == "learned" and flight.learned:
            # The Pilot Lab's network flies from the camera alone (same 0.25 s step it trained on).
            name, net = flight.learned
            action = net.act(lp_prev if lp_prev is not None else lab_gray(lab_view), lab_view, chunk.action)
            by, why = "autopilot", f"learned pilot {name}: {action.replace('_', ' ')} (from pixels)"
        elif flight.autopilot:
            (action, why), by = pilot.decide(p, chunk.action, a), "autopilot"
        else:
            action, by, why = "hover", "idle", "no input"
        await world.act(action)

        decision = {"n": flight.counts["decisions"], "k": chunk.index, "t": round(time.perf_counter() - t0, 2), "action": action, "by": by,
                    "why": why, "verdict": a.verdict, "reasons": a.reasons[:3], "active": chunk.action,
                    "danger": round(a.danger, 3), "presence": round(a.presence, 3),
                    "obedience": round(a.obedience, 3) if a.obedience is not None else None,
                    "hazards": [asdict(h) for h in a.hazards[:6]],
                    "physics": {k2: flight.physics[k2] for k2 in ("t", "speed_ms", "altitude_m", "battery_pct", "heading_deg", "tilt_deg")}}
        flight.decisions.append(decision)
        flight.assessment = a.to_dict()
        flight.last_reason = why
        flight.counts["decisions"] += 1
        flight.counts[by] = flight.counts.get(by, 0) + 1
        if a.verdict != "clear":
            flight.counts[a.verdict] += 1
        if SEVERITY[a.verdict] >= SEVERITY["warning"]:
            last = flight.alerts[-1] if flight.alerts else None
            if not last or last["verdict"] != a.verdict or chunk.index - last["k"] >= 4:
                flight.alerts.append({"n": flight.counts["decisions"], "k": chunk.index, "verdict": a.verdict, "reasons": a.reasons[:3],
                                      "action": action, "by": by, "thumb": _thumb(hires),
                                      "narration": (flight.narration or {}).get("text")})
        if narrator:
            narrator.offer(hires)
            flight.narration = narrator.latest
        telemetry.last = {"chunk": chunk.index, "action": action, "controller": by, "label": action, "reason": why}
        telemetry.usage = world.usage()
        if getattr(world, "on_display", None) is None:
            telemetry.frame(hires)  # worlds with on_display stream their own frames at display rate

        score["chunks"] += 1
        score["forward"] += chunk.action in ("forward", "arc_left", "arc_right")
        for v in ("warning", "collision", "anomaly"):
            score[v] += a.verdict == v
        if chunk.info.get("collided"):
            score["crashed_truth"] = True
        if rec:
            rec.add({"chunk": chunk.index, **{x: decision[x] for x in ("action", "by", "why", "verdict", "reasons",
                                                                        "danger", "presence", "obedience")},
                     "active": chunk.action, "truth": chunk.info}, cur, hires)
        prev = cur
        if chunk.info.get("collided"):
            flight.counts["crashes"] = flight.counts.get("crashes", 0) + 1
            if not respawn:
                telemetry.say("mock world: real collision (ground truth); ending this flight")
                break
            telemetry.say("mock world: real collision (ground truth); respawning")
            scene.seed += 1
            twin.respawn()
            first = await world.start(scene)
            prev = prep(first) if first is not None else None
            sentinel.reset()


def tune_score(s: dict) -> float:
    """Physical distance flown (MuJoCo), minus what the Sentinel (or the mock's ground truth) called."""
    return round(2 * s.get("distance_m", s["forward"]) - 2 * s["warning"] - 10 * s["collision"] - 5 * s["anomaly"]
                 - (30 if s["crashed_truth"] else 0), 1)


def candidates(kind: str = "mock") -> list[PilotParams]:
    base = PilotParams.load(kind) if kind == "reactor" else PilotParams()
    out = []
    for veer in ((0.35, 0.45, 0.6) if kind == "reactor" else (0.12, 0.2, 0.3)):
        for yield_gap in (0.5, 1.0):
            out.append(PilotParams(veer=veer, spin=max(base.spin, veer + 0.2), balance=base.balance, yield_gap=yield_gap))
    return out


async def autotune(world: World, scene_key: str, flight: FlightState, telemetry, *, flights_per: int = 3,
                   max_chunks: int = 30) -> dict:
    """Score every candidate on the same seeds, keep the best, save it as the autopilot."""
    from . import budget

    flight.tune = []
    sentinel = await asyncio.to_thread(Sentinel, WORLDS[scene_key], kind=world.kind)
    grid = candidates(world.kind)
    best = None
    for i, params in enumerate(grid):
        scores = []
        try:
            for f in range(flights_per):
                if telemetry.stop_requested:
                    break
                telemetry.detail = f"auto-tune {i + 1}/{len(grid)}, flight {f + 1}/{flights_per}"
                scores.append(await fly(world, scene_key, flight, telemetry, params=params, max_chunks=max_chunks,
                                        seed=100 + f, record=False, narrate=False, sentinel=sentinel))
        except budget.BudgetExceeded as e:
            telemetry.say(f"{e}; scoring what was flown")
        if not scores:
            break
        row = {"params": asdict(params), "flights": len(scores), "score": round(float(np.mean([tune_score(s) for s in scores])), 1),
               "forward": round(float(np.mean([s.get("distance_m", s["forward"]) for s in scores])), 1),
               "warnings": sum(s["warning"] for s in scores), "collisions": sum(s["collision"] for s in scores),
               "crashes_truth": sum(s["crashed_truth"] for s in scores)}
        flight.tune.append(row)
        telemetry.say(f"auto-tune {i + 1}: veer {params.veer} yield {params.yield_gap} -> score {row['score']}")
        if best is None or row["score"] > best["score"]:
            best = row
        if telemetry.stop_requested:
            break
    if best:
        saved = json.loads(PILOT_FILE.read_text(encoding="utf-8")) if PILOT_FILE.exists() else {}
        saved = saved if "params" not in saved else {}  # drop the old single-entry format
        saved[world.kind] = {"params": best["params"], "score": best["score"], "scene": scene_key,
                             "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        PILOT_FILE.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        flight.params = best["params"]
        telemetry.say(f"auto-tune: kept veer {best['params']['veer']} yield {best['params']['yield_gap']} "
                      f"(score {best['score']}) as the autopilot")
    return {"best": best, "rows": flight.tune}
