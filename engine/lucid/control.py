"""PX4-style cascaded flight controller, from pilot command to motor speeds.

    command (forward / turn / climb ...) -> velocity + yaw-rate setpoint      (pilot layer)
    velocity P   -> acceleration setpoint (tilt-limited)                      (MPC_XY_P / MPC_Z_P)
    acceleration -> attitude (rotation) + collective thrust setpoint
    attitude P   -> body-rate setpoint                                         (MC_*_P)
    rate PID     -> body torque                                                (MC_*RATE_P/I/D)
    allocation   -> motor speeds (inverse of the physics' thrust/torque map)   (mixer / control allocation)

Every gain lives in `Gains`: these are the controller's weights, and the ones auto-tune and the
calibration loop adjust between flights.
"""
from dataclasses import asdict, dataclass, field

import numpy as np

from .physics import G, Quadrotor


@dataclass
class Gains:
    vel_xy_p: float = 1.8  # 1/s
    vel_z_p: float = 3.0
    att_p: float = 7.0  # 1/s, roll/pitch
    yaw_p: float = 3.0
    rate_p: np.ndarray = field(default_factory=lambda: np.array([0.15, 0.15, 0.25]))  # torque per rad/s per inertia unit
    rate_i: np.ndarray = field(default_factory=lambda: np.array([0.05, 0.05, 0.05]))
    rate_d: np.ndarray = field(default_factory=lambda: np.array([0.003, 0.003, 0.0]))
    tilt_max_deg: float = 35.0  # MPC_TILTMAX_AIR

    def to_dict(self) -> dict:
        return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in asdict(self).items()}


@dataclass
class CommandProfile:
    """What each discrete pilot command means physically. Cruise speeds are tunable weights."""

    cruise_ms: float = 2.5
    back_ms: float = 1.2
    strafe_ms: float = 1.2
    yaw_rate_dps: float = 45.0
    climb_ms: float = 1.0  # spec allows 6 up / 2 down; kept gentle indoors
    descend_ms: float = 0.8

    def setpoint(self, action: str) -> tuple[np.ndarray, float]:
        """Body-frame velocity (vx forward, vy left, vz up) and yaw rate (rad/s, + = left)."""
        v, r = np.zeros(3), 0.0
        yaw = np.radians(self.yaw_rate_dps)
        if action == "forward":
            v[0] = self.cruise_ms
        elif action == "back":
            v[0] = -self.back_ms
        elif action == "left":
            v[1] = self.strafe_ms
        elif action == "right":
            v[1] = -self.strafe_ms
        elif action == "yaw_left":
            r = yaw
        elif action == "yaw_right":
            r = -yaw
        elif action == "arc_left":
            v[0], r = 0.8 * self.cruise_ms, 0.7 * yaw
        elif action == "arc_right":
            v[0], r = 0.8 * self.cruise_ms, -0.7 * yaw
        elif action == "up":
            v[2] = self.climb_ms
        elif action == "down":
            v[2] = -self.descend_ms
        return v, r


def _vee(m):
    return np.array([m[2, 1], m[0, 2], m[1, 0]])


class FlightController:
    def __init__(self, quad: Quadrotor, gains: Gains | None = None):
        self.q = quad
        self.g = gains or Gains()
        p = quad.p
        d = p.arm / np.sqrt(2)
        # Rows: thrust, roll, pitch, yaw torque as a linear map of the four (kf w^2) thrusts.
        self.A = np.array([
            [1, 1, 1, 1],
            [d, -d, -d, d],
            [-d, -d, d, d],
            (Quadrotor._SPIN * p.km / p.kf),
        ], dtype=float)
        self.A_inv = np.linalg.inv(self.A)
        self.yaw_sp = quad.yaw
        self.i_rate = np.zeros(3)
        self.prev_rate_err = np.zeros(3)

    def update(self, v_body_sp: np.ndarray, yaw_rate_sp: float, dt: float) -> np.ndarray:
        q, g, p = self.q, self.g, self.q.p
        # --- velocity loop (world frame, heading-aligned setpoint)
        self.yaw_sp += yaw_rate_sp * dt
        c, s = np.cos(self.yaw_sp), np.sin(self.yaw_sp)
        v_sp = np.array([c * v_body_sp[0] - s * v_body_sp[1], s * v_body_sp[0] + c * v_body_sp[1], v_body_sp[2]])
        err = v_sp - q.vel
        a_sp = np.array([g.vel_xy_p * err[0], g.vel_xy_p * err[1], g.vel_z_p * err[2]])
        # Drag feedforward so cruise speed is actually reached.
        a_sp += p.drag * np.linalg.norm(v_sp) * v_sp / p.mass
        # --- tilt limit: horizontal acceleration bounded by the max tilt at the needed lift
        a_z = a_sp[2] + G
        h_max = max(a_z, 0.1) * np.tan(np.radians(g.tilt_max_deg))
        h = np.linalg.norm(a_sp[:2])
        if h > h_max:
            a_sp[:2] *= h_max / h
        thrust_vec = p.mass * np.array([a_sp[0], a_sp[1], a_z])
        # --- desired attitude: body z along the thrust vector, heading from the yaw setpoint
        zb = thrust_vec / np.linalg.norm(thrust_vec)
        xc = np.array([c, s, 0.0])
        yb = np.cross(zb, xc)
        yb /= np.linalg.norm(yb)
        xb = np.cross(yb, zb)
        R_sp = np.column_stack([xb, yb, zb])
        T = float(thrust_vec @ q.R[:, 2])  # collective thrust projected on the current body z
        # --- attitude loop -> body-rate setpoint
        e_R = 0.5 * _vee(R_sp.T @ q.R - q.R.T @ R_sp)
        rate_sp = -np.array([g.att_p, g.att_p, g.yaw_p]) * e_R
        # --- rate PID -> torque
        e_w = rate_sp - q.omega
        self.i_rate = np.clip(self.i_rate + e_w * dt, -0.5, 0.5)  # anti-windup
        d_w = (e_w - self.prev_rate_err) / dt
        self.prev_rate_err = e_w
        tau = q.J @ (np.array([60.0, 60.0, 40.0]) * (g.rate_p * e_w + g.rate_i * self.i_rate + g.rate_d * d_w))
        tau += np.cross(q.omega, q.J @ q.omega)
        # --- allocation: four thrusts, then motor speeds
        f = self.A_inv @ np.array([max(T, 0.0), tau[0], tau[1], tau[2]])
        f = np.clip(f, 0.0, p.kf * p.w_max ** 2)
        return np.sqrt(f / p.kf)
