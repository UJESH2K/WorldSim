"""The digital twin: physics decides, the world renders, and a calibration loop keeps them honest.

    pilot command --> FlightController --> Quadrotor physics (400 Hz)   = what physically happened
                                               |
                                               v
                        world renders it:  mock / photo: moved exactly by the physics state
                                           LingBot:      driven by commands, rotation speed set
                                                         from the physics' yaw rate / k_yaw
                                               |
    optical flow on the rendered frames  ------+--> Calibrator: rendered motion vs physics motion
                                                    -> k_yaw weight, speed-tracking correlation,
                                                       updated after every flight (persisted)

The Calibrator's weights are the "learned" part that gets more precise with every flight: the
mock world, where render and physics agree by construction, must converge to k_yaw = 1, which is
how the estimator itself is validated before its LingBot numbers are trusted.
"""
import json
import time
from dataclasses import dataclass

import numpy as np

from .config import DATA
from .control import CommandProfile, FlightController, Gains
from .config import env
from .physics import QuadParams, Quadrotor


def make_quad(params: QuadParams | None = None, altitude: float = 1.2, hz: int = 400, engine: str | None = None) -> Quadrotor:
    """MuJoCo by default (the robotics standard); LUCID_PHYSICS=builtin selects the reference model."""
    if (engine or env("LUCID_PHYSICS", "mujoco")) != "builtin":
        try:
            from .mujoco_quad import MujocoQuadrotor

            return MujocoQuadrotor(params, altitude=altitude, dt=1.0 / hz)
        except ImportError:
            pass
    return Quadrotor(params, altitude=altitude)

PHYSICS_HZ = 400
CALIB_FILE = DATA / "calibration.json"
REPORTS = DATA / "reports"


@dataclass
class Motion:
    forward_m: float  # along the heading at the start of the step
    left_m: float
    up_m: float
    yaw_rad: float  # + = left
    seconds: float


class PhysicsTwin:
    def __init__(self, params: QuadParams | None = None, gains: Gains | None = None,
                 profile: CommandProfile | None = None, altitude: float = 1.2, hz: int | None = None,
                 engine: str | None = None):
        self.hz = hz or PHYSICS_HZ
        self.quad = make_quad(params, altitude, self.hz, engine)
        self.engine = getattr(self.quad, "engine", "built-in Newton-Euler")
        self.fc = FlightController(self.quad, gains)
        self.profile = profile or CommandProfile()
        self.distance_m = 0.0
        self.max_speed = 0.0
        self.max_tilt = 0.0

    def advance(self, action: str, seconds: float) -> Motion:
        """Fly `action` for `seconds` of physical time; return the motion in the start frame."""
        q = self.quad
        p0, yaw0 = q.pos.copy(), q.yaw
        v_sp, r_sp = self.profile.setpoint(action)
        dt = 1.0 / self.hz
        n = max(1, int(round(seconds * self.hz)))
        for _ in range(n):
            prev = q.pos.copy()
            q.step(self.fc.update(v_sp, r_sp, dt), dt)
            self.distance_m += float(np.linalg.norm(q.pos - prev))
        self.max_speed = max(self.max_speed, float(np.linalg.norm(q.vel)))
        self.max_tilt = max(self.max_tilt, q.tilt_deg)
        d = q.pos - p0
        c, s = np.cos(yaw0), np.sin(yaw0)
        dyaw = float(np.arctan2(np.sin(q.yaw - yaw0), np.cos(q.yaw - yaw0)))
        return Motion(forward_m=float(c * d[0] + s * d[1]), left_m=float(-s * d[0] + c * d[1]),
                      up_m=float(d[2]), yaw_rad=dyaw, seconds=n * dt)

    def respawn(self, altitude: float = 1.2):
        """Back to the start pose after a crash; energy used and distance flown carry over."""
        energy, t = self.quad.energy_wh, self.quad.t
        self.quad.reset(altitude)
        self.quad.energy_wh, self.quad.t = energy, t
        self.fc = FlightController(self.quad, self.fc.g)

    def telemetry(self) -> dict:
        return {**self.quad.telemetry(), "distance_m": round(self.distance_m, 2), "engine": self.engine}


class Calibrator:
    """Learns how the renderer's motion relates to the physics' motion, per world kind."""

    def __init__(self, kind: str):
        self.kind = kind
        self.saved = json.loads(CALIB_FILE.read_text(encoding="utf-8")).get(kind, {}) if CALIB_FILE.exists() else {}
        self.yaw_pairs: list[tuple[float, float]] = []  # (physics dyaw, rendered dyaw), radians
        self.speed_pairs: list[tuple[float, float]] = []  # (physics forward speed, rendered expansion)

    @property
    def k_yaw(self) -> float:
        """Current best weight: rendered yaw per unit of physical yaw (1.0 = they agree)."""
        return float(self.saved.get("k_yaw", 1.0))

    def observe(self, motion: Motion, perception) -> None:
        if perception is None or motion.seconds <= 0:
            return
        # Rendered yaw from the flow's mean horizontal shift; the scene slides right (+u) when
        # turning left. Normalised u = tan(angle) for a 90 degree lens; k_yaw absorbs other lenses.
        rendered_yaw = float(np.arctan(perception.u))
        # Sideways travel slides the image the same way a turn does, so those steps are left out.
        # Forward coasting (inertia carries the drone on while it turns) mostly expands the image
        # instead, so it stays in.
        if abs(motion.yaw_rad) > np.radians(2) and abs(motion.left_m) < 0.03:
            self.yaw_pairs.append((motion.yaw_rad, rendered_yaw))
        if motion.forward_m > 0.02 and abs(motion.yaw_rad) < np.radians(3):
            self.speed_pairs.append((motion.forward_m / motion.seconds, perception.sx + perception.sy))

    def flight_estimate(self) -> dict:
        out = {"yaw_samples": len(self.yaw_pairs), "speed_samples": len(self.speed_pairs)}
        if len(self.yaw_pairs) >= 3:
            p, r = np.array(self.yaw_pairs).T
            out["k_yaw"] = round(float((p * r).sum() / (p * p).sum()), 3)  # least squares through 0
            resid = r - out["k_yaw"] * p
            out["yaw_fit_r2"] = round(float(1 - (resid ** 2).sum() / max(1e-9, ((r - r.mean()) ** 2).sum())), 3)
        if len(self.speed_pairs) >= 4:
            v, e = np.array(self.speed_pairs).T
            if v.std() > 1e-3 and e.std() > 1e-6:
                out["speed_tracking_corr"] = round(float(np.corrcoef(v, e)[0, 1]), 3)
        return out

    def commit(self) -> dict:
        """Fold this flight's estimate into the saved weights (sample-weighted running mean)."""
        est = self.flight_estimate()
        if "k_yaw" in est:
            n_old = self.saved.get("yaw_samples", 0)
            n_new = est["yaw_samples"]
            k = (self.k_yaw * n_old + est["k_yaw"] * n_new) / (n_old + n_new)
            history = self.saved.get("history", []) + [{"at": time.strftime("%Y-%m-%d %H:%M"), "k_yaw": est["k_yaw"],
                                                        "samples": n_new, "r2": est.get("yaw_fit_r2")}]
            self.saved = {"k_yaw": round(k, 3), "yaw_samples": n_old + n_new, "history": history[-30:]}
            data = json.loads(CALIB_FILE.read_text(encoding="utf-8")) if CALIB_FILE.exists() else {}
            data[self.kind] = self.saved
            CALIB_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {**est, "k_yaw_saved": self.k_yaw, "flights_calibrated": len(self.saved.get("history", []))}


# ---------------------------------------------------------------------------- flight report
CHECKS = [
    # (id, plain-language requirement, metric key, comparison, threshold)
    ("no_collision", "No collision called", "collisions", "==", 0),
    ("separation", "Kept at least 0.5 m from people and objects", "min_separation_m", ">=", 0.5),
    ("battery", "Landed with at least 20% battery", "battery_end_pct", ">=", 20.0),
    ("world_valid", "World model stayed trustworthy (under 5% of steps flagged)", "anomaly_rate", "<=", 0.05),
    ("tilt", "Stayed inside the 35 degree tilt envelope", "max_tilt_deg", "<=", 35.5),
]
DRONE_WIDTH_M = 0.35  # Phantom 2 diagonal, used to turn image gaps (in drone-widths) into metres


def build_report(flight_id: str, scene: dict, world_kind: str, twin: PhysicsTwin, decisions: list,
                 calibration: dict, params: dict, world_audit: dict | None = None) -> dict:
    tel = twin.telemetry()
    n = max(1, len(decisions))
    gaps = [h["gap"] for d in decisions for h in d.get("hazards", []) if h.get("zone") in ("touching", "close", "ahead", "far")]
    counts = {v: sum(d["verdict"] == v for d in decisions) for v in ("clear", "caution", "warning", "collision", "anomaly")}
    metrics = {
        "duration_s": tel["t"],
        "decisions": len(decisions),
        "decision_rate_hz": round(len(decisions) / max(tel["t"], 1e-6), 2),
        "distance_m": tel["distance_m"],
        "max_speed_ms": round(twin.max_speed, 2),
        "max_tilt_deg": round(twin.max_tilt, 1),
        "energy_wh": tel["energy_wh"],
        "battery_end_pct": tel["battery_pct"],
        "collisions": counts["collision"],
        "warnings": counts["warning"],
        "anomaly_rate": round(counts["anomaly"] / n, 3),
        "min_separation_m": round(min(gaps) * DRONE_WIDTH_M, 2) if gaps else None,
        "human_share": round(sum(d["by"] == "human" for d in decisions) / n, 3),
        "obedience_mean": round(float(np.mean([d["obedience"] for d in decisions if d.get("obedience") is not None] or [0])), 3),
    }
    checks = []
    for cid, text, key, op, thr in CHECKS:
        val = metrics.get(key)
        ok = None if val is None else (val == thr if op == "==" else val >= thr if op == ">=" else val <= thr)
        checks.append({"id": cid, "requirement": text, "value": val, "threshold": f"{op} {thr}", "pass": ok})
    verdict = "PASS" if all(c["pass"] is not False for c in checks) else "FAIL"
    recs = []
    if metrics["collisions"]:
        recs.append("Raise the yield gap or lower cruise speed, then run auto-tune on this place.")
    if metrics["min_separation_m"] is not None and metrics["min_separation_m"] < 0.5:
        recs.append("Separation fell below 0.5 m: widen the autopilot's veer sensitivity.")
    if metrics["anomaly_rate"] > 0.05:
        recs.append("The world model drifted often: shorten flights or use a clearer photo and description.")
    if calibration.get("speed_tracking_corr") is not None and calibration["speed_tracking_corr"] < 0.3:
        recs.append("Rendered speed does not follow physical speed in this world; trust the physics for speed and distance.")
    if not recs:
        recs.append("No changes needed; fly a harder scenario (events, other places) to widen coverage.")
    report = {
        "id": flight_id, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "world": world_kind, "scene": scene,
        "verdict": verdict, "metrics": metrics, "checks": checks, "counts": counts,
        "calibration": calibration, "recommendations": recs,
        "model": {"airframe": "Phantom 2 class quadrotor", "engine": twin.engine, "physics": QuadParams().to_dict(),
                  "controller": twin.fc.g.to_dict(), "command_profile": twin.profile.__dict__, "autopilot": params},
        # t is physics time, like the metrics
        "trace": [{"n": d["n"], "t": d.get("physics", {}).get("t", d["t"]), "action": d["action"], "by": d["by"], "verdict": d["verdict"],
                   "speed_ms": d.get("physics", {}).get("speed_ms"), "battery_pct": d.get("physics", {}).get("battery_pct")}
                  for d in decisions],
        "world_audit": world_audit,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{flight_id}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
