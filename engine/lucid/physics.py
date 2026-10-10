"""Quadrotor rigid-body dynamics: the source of truth for the drone's state.

The world model renders; this decides what physically happened. Standard 6-DoF Newton-Euler
model, as in gym-pybullet-drones and RotorS:

    motor i:      w_i' = (w_cmd_i - w_i) / tau          first-order motor lag
                  f_i = kf * w_i^2,  q_i = km * w_i^2    thrust and drag torque
    translation:  m a = R e3 * sum(f_i) - m g e3 - c_d |v| v
    rotation:     J w' = tau - w x (J w)                  tau from the X-configuration arms
    battery:      P = P_hover * (T / m g)^1.5             momentum-theory scaling

Parameters are a DJI Phantom 2 class drone (the one on screen): 1.0 kg, 350 mm motor-to-motor
diagonal, about 25 min hover on a 57.7 Wh pack, 15 m/s top speed (DJI spec sheet). Inertia,
kf/km and the drag coefficient are derived from those numbers, documented below.

World frame: x forward at take-off, y left, z up (metres). Body frame: x nose, y left, z up.
"""
from dataclasses import asdict, dataclass

import numpy as np

G = 9.81


@dataclass
class QuadParams:
    mass: float = 1.0  # kg, Phantom 2 with battery and props
    arm: float = 0.175  # m, centre to motor (350 mm diagonal / 2)
    kf: float = 1.0e-5  # N/(rad/s)^2: hover at ~495 rad/s (~4,700 rpm)
    km: float = 1.6e-7  # N m/(rad/s)^2: km/kf = 0.016 m, typical for 9-10 inch props
    ixx: float = 0.011  # kg m^2, typical for a 1 kg, 350 mm quad
    iyy: float = 0.011
    izz: float = 0.021
    motor_tau: float = 0.03  # s, motor and ESC response
    w_max: float = 700.0  # rad/s: thrust-to-weight 2.0
    drag: float = 0.031  # N s^2/m^2: 15 m/s at ~35 deg tilt, matching the spec top speed
    battery_wh: float = 57.7  # 5200 mAh x 11.1 V
    hover_power_w: float = 138.0  # 57.7 Wh over the spec's 25 min hover

    def to_dict(self) -> dict:
        return asdict(self)


def _hat(w):
    return np.array([[0, -w[2], w[1]], [w[2], 0, -w[0]], [-w[1], w[0], 0]])


def _expm_so3(phi):
    """Rotation matrix for a rotation vector (Rodrigues)."""
    th = np.linalg.norm(phi)
    if th < 1e-9:
        return np.eye(3) + _hat(phi)
    k = _hat(phi / th)
    return np.eye(3) + np.sin(th) * k + (1 - np.cos(th)) * k @ k


class Quadrotor:
    def __init__(self, params: QuadParams | None = None, altitude: float = 1.2, yaw: float = 0.0):
        self.p = params or QuadParams()
        self.J = np.diag([self.p.ixx, self.p.iyy, self.p.izz])
        self.J_inv = np.linalg.inv(self.J)
        self.reset(altitude, yaw)

    def reset(self, altitude: float = 1.2, yaw: float = 0.0):
        c, s = np.cos(yaw), np.sin(yaw)
        self.pos = np.array([0.0, 0.0, altitude])
        self.vel = np.zeros(3)
        self.R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        self.omega = np.zeros(3)  # body rates
        w_hover = self.hover_speed()
        self.w = np.full(4, w_hover)  # motor speeds, rad/s
        self.energy_wh = 0.0
        self.t = 0.0
        self.on_ground = False

    def hover_speed(self) -> float:
        return float(np.sqrt(self.p.mass * G / (4 * self.p.kf)))

    # Motor layout, X configuration seen from above: 0 front-left (CCW), 1 front-right (CW),
    # 2 back-right (CCW), 3 back-left (CW). Spin direction sets the sign of each drag torque.
    _SPIN = np.array([1, -1, 1, -1])

    def forces(self):
        f = self.p.kf * self.w ** 2
        T = f.sum()
        d = self.p.arm / np.sqrt(2)
        tau = np.array([
            d * (f[0] + f[3] - f[1] - f[2]),  # roll: left motors push the left side up
            d * (f[2] + f[3] - f[0] - f[1]),  # pitch: back motors push the nose down
            float((self._SPIN * self.p.km * self.w ** 2).sum()),  # yaw from rotor drag
        ])
        return T, tau

    def step(self, w_cmd: np.ndarray, dt: float):
        p = self.p
        w_cmd = np.clip(w_cmd, 0.0, p.w_max)
        self.w += (w_cmd - self.w) * min(1.0, dt / p.motor_tau)
        T, tau = self.forces()
        acc = (self.R[:, 2] * T - np.array([0, 0, p.mass * G]) - p.drag * np.linalg.norm(self.vel) * self.vel) / p.mass
        domega = self.J_inv @ (tau - np.cross(self.omega, self.J @ self.omega))
        # Semi-implicit Euler at high rate: velocity first, then position (stable at 400 Hz).
        self.vel += acc * dt
        self.pos += self.vel * dt
        self.omega += domega * dt
        self.R = self.R @ _expm_so3(self.omega * dt)
        u, _, vt = np.linalg.svd(self.R)  # keep R orthonormal
        self.R = u @ vt
        if self.pos[2] <= 0.0:  # ground contact
            self.pos[2] = 0.0
            self.vel[2] = max(0.0, self.vel[2])
            self.vel[:2] *= 0.5
            self.on_ground = True
        else:
            self.on_ground = False
        power = p.hover_power_w * max(0.0, T / (p.mass * G)) ** 1.5
        self.energy_wh += power * dt / 3600.0
        self.t += dt
        return acc

    # ---- readouts --------------------------------------------------------------------------
    @property
    def yaw(self) -> float:
        return float(np.arctan2(self.R[1, 0], self.R[0, 0]))

    @property
    def tilt_deg(self) -> float:
        return float(np.degrees(np.arccos(np.clip(self.R[2, 2], -1, 1))))

    def body_velocity(self) -> np.ndarray:
        return self.R.T @ self.vel

    def battery_pct(self) -> float:
        return float(max(0.0, 100.0 * (1 - self.energy_wh / self.p.battery_wh)))

    def power_w(self) -> float:
        T, _ = self.forces()
        return float(self.p.hover_power_w * max(0.0, T / (self.p.mass * G)) ** 1.5)

    def telemetry(self) -> dict:
        roll = float(np.degrees(np.arctan2(self.R[2, 1], self.R[2, 2])))
        pitch = float(np.degrees(-np.arcsin(np.clip(self.R[2, 0], -1, 1))))
        return {
            "t": round(self.t, 2),
            "pos_m": [round(float(x), 2) for x in self.pos],
            "speed_ms": round(float(np.linalg.norm(self.vel)), 2),
            "vz_ms": round(float(self.vel[2]), 2),
            "altitude_m": round(float(self.pos[2]), 2),
            "heading_deg": round(float(np.degrees(self.yaw)) % 360, 1),
            "roll_deg": round(roll, 1),
            "pitch_deg": round(pitch, 1),
            "tilt_deg": round(self.tilt_deg, 1),
            "motor_rpm": [int(w * 60 / (2 * np.pi)) for w in self.w],
            "power_w": round(self.power_w(), 1),
            "battery_pct": round(self.battery_pct(), 2),
            "energy_wh": round(self.energy_wh, 4),
        }
