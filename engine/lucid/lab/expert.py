"""Privileged expert: plans with the ground truth the pilot never sees.

For each candidate command it predicts the next 1.5 s of flight with a kinematic model of the
drone (the commanded speeds and turn rates of lucid.control.CommandProfile, first-order speed
response matching the physics' measured 1.0 s to 90%, and one step of control latency), then
scores the path: progress made, minus a large penalty if it passes closer to an obstacle than
the drone's radius plus a margin. The pilot is trained to imitate these choices from pixels.
"""
import numpy as np

from ..control import CommandProfile

CANDIDATES = ["forward", "arc_left", "arc_right", "yaw_left", "yaw_right", "hover", "back"]
DRONE_RADIUS = 0.3
MARGIN = 0.35
SPEED_TAU = 0.6  # s; physics braking measured slower than speeding up (tilt-limited)
STEP = 0.25  # s per decision
HORIZON = 6  # decisions ahead (1.5 s)
SUB = 3  # integration substeps per decision


class Expert:
    def __init__(self, profile: CommandProfile | None = None):
        p = profile or CommandProfile()
        yaw = np.radians(p.yaw_rate_dps)
        self.cmd = {  # forward speed (m/s), yaw rate (rad/s)
            "hover": (0.0, 0.0), "forward": (p.cruise_ms, 0.0), "back": (-p.back_ms, 0.0),
            "arc_left": (0.8 * p.cruise_ms, 0.7 * yaw), "arc_right": (0.8 * p.cruise_ms, -0.7 * yaw),
            "yaw_left": (0.0, yaw), "yaw_right": (0.0, -yaw),
            "left": (0.0, 0.0), "right": (0.0, 0.0), "up": (0.0, 0.0), "down": (0.0, 0.0),
        }

    def _rollout(self, pos, heading, speed, active, action, C, R):
        """Path points for: `active` for one step (latency), then `action` for the rest."""
        pts = []
        x, y, h, v = float(pos[0]), float(pos[1]), float(heading), float(speed)
        dt = STEP / SUB
        for k in range(HORIZON):
            v_sp, r = self.cmd[active if k == 0 else action]
            for _ in range(SUB):
                v = v_sp + (v - v_sp) * np.exp(-dt / SPEED_TAU)
                h += r * dt
                x += v * np.cos(h) * dt
                y += v * np.sin(h) * dt
                pts.append((x, y))
        return np.array(pts)

    def choose(self, pos, heading, speed, active, C, R) -> tuple[str, dict]:
        scores = {}
        for a in CANDIDATES:
            path = self._rollout(pos, heading, speed, active, a, C, R)
            if len(C):
                d = np.linalg.norm(path[:, None, :] - C[None, :, :], axis=2) - R[None, :]
                clear = float(d.min())
            else:
                clear = 9.0
            progress = float(np.linalg.norm(path[-1] - np.asarray(pos)))
            if a == "back":
                progress *= 0.3  # reversing is a last resort
            # Clearance only matters once something is close: otherwise prefer plain progress, so the
            # labels are decisive (go straight unless there is a reason not to).
            score = progress + 1.0 * min(clear, 1.2)
            if clear < DRONE_RADIUS + MARGIN:
                score -= 100.0 - 50.0 * max(clear, 0.0)  # unsafe: least-bad if everything is unsafe
            scores[a] = round(score, 3)
        best = max(scores, key=scores.get)
        return best, scores
