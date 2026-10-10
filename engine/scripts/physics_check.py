"""Physics validation: both backends against the Phantom 2 spec and against each other.

    python scripts/physics_check.py

Hover power and endurance, step response, yaw tracking, top speed at the tilt limit, and a
straight-line trajectory flown by both backends with the difference reported.
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lucid.control import CommandProfile, FlightController  # noqa: E402
from lucid.physics import Quadrotor  # noqa: E402

DT = 1 / 400
BACKENDS = {"built-in": Quadrotor}
try:
    from lucid.mujoco_quad import MujocoQuadrotor  # noqa: E402

    BACKENDS["MuJoCo"] = MujocoQuadrotor
except ImportError:
    pass


def fly(cls, plan, v_override=None):
    q = cls()
    fc = FlightController(q)
    prof = CommandProfile()
    track = []
    for action, seconds in plan:
        v, r = prof.setpoint(action)
        if v_override is not None:
            v = v_override
        for _ in range(int(seconds / DT)):
            q.step(fc.update(v, r, DT), DT)
            track.append(q.pos.copy())
    return q, np.array(track)


def main():
    results = {}
    for name, cls in BACKENDS.items():
        t0 = time.perf_counter()
        r = {}
        q, _ = fly(cls, [("hover", 10)])
        r["hover alt (m)"] = round(float(q.pos[2]), 3)
        r["hover power (W)"] = round(q.power_w(), 1)
        r["endurance (min)"] = round(q.p.battery_wh / q.power_w() * 60, 1)
        q = cls()
        fc = FlightController(q)
        v, _ = CommandProfile().setpoint("forward")
        t90 = None
        for i in range(int(4 / DT)):
            q.step(fc.update(v, 0.0, DT), DT)
            if t90 is None and q.body_velocity()[0] >= 0.9 * v[0]:
                t90 = (i + 1) * DT
        r["0 to 90% of 2.5 m/s (s)"] = round(t90, 2)
        q, _ = fly(cls, [("yaw_left", 2)])
        r["yaw in 2 s at 45 deg/s (deg)"] = round(float(np.degrees(q.yaw)), 1)
        q, _ = fly(cls, [("hover", 0.1)], v_override=np.array([25.0, 0, 0]))
        q2 = cls()
        fc2 = FlightController(q2)
        for _ in range(int(15 / DT)):
            q2.step(fc2.update(np.array([25.0, 0, 0]), 0.0, DT), DT)
        r["top speed (m/s)"] = round(float(np.linalg.norm(q2.vel)), 2)
        r["tilt at top speed (deg)"] = round(q2.tilt_deg, 1)
        r["sim time per real second"] = round(15 / (time.perf_counter() - t0), 1)
        results[name] = r

    keys = list(next(iter(results.values())))
    spec = {"endurance (min)": "~25", "top speed (m/s)": "15", "tilt at top speed (deg)": "35 (limit)"}
    print(f"{'check':34s}" + "".join(f"{n:>12s}" for n in results) + f"{'spec':>14s}")
    for k in keys:
        print(f"{k:34s}" + "".join(f"{results[n][k]:>12}" for n in results) + f"{spec.get(k, ''):>14s}")

    if len(BACKENDS) == 2:
        plan = [("forward", 3), ("arc_left", 2), ("up", 1), ("yaw_right", 1.5), ("forward", 2), ("hover", 1)]
        _, a = fly(BACKENDS["built-in"], plan)
        _, b = fly(BACKENDS["MuJoCo"], plan)
        err = np.linalg.norm(a - b, axis=1)
        print(f"\nsame 10.5 s manoeuvre on both backends: path {np.sum(np.linalg.norm(np.diff(a, axis=0), axis=1)):.1f} m, "
              f"max position difference {err.max() * 100:.1f} cm, final {err[-1] * 100:.1f} cm")


if __name__ == "__main__":
    main()
