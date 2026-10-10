"""MuJoCo backend for the quadrotor: the same airframe and controller, integrated by MuJoCo.

MuJoCo (DeepMind) is the standard physics engine for robotics and RL. Here it integrates the
rigid-body dynamics (RK4 at 400 Hz) and handles contact with the ground; the four motors are
site actuators whose gear applies both thrust and each rotor's reaction (yaw) torque:

    gear = [0, 0, 1, 0, 0, spin_i * km/kf]   ->  thrust f_i along the motor axis, torque spin_i * km/kf * f_i

Motor lag, quadratic drag and the battery are applied around mj_step exactly as in the built-in
model (lucid.physics), so the two backends can be checked against each other.
"""
import mujoco
import numpy as np

from .physics import G, QuadParams, Quadrotor


def build_mjcf(p: QuadParams, dt: float) -> str:
    d = p.arm / np.sqrt(2)
    f_max = p.kf * p.w_max ** 2
    motors = [(d, d), (d, -d), (-d, -d), (-d, d)]  # front-left, front-right, back-right, back-left
    sites = "\n".join(f'<site name="m{i}" pos="{x:.4f} {y:.4f} 0.02" size="0.01"/>' for i, (x, y) in enumerate(motors))
    rotors = "\n".join(f'<geom type="cylinder" pos="{x:.4f} {y:.4f} 0.03" size="0.12 0.005" rgba="0.8 0.8 0.8 0.4"/>'
                       for x, y in motors)
    acts = "\n".join(f'<motor site="m{i}" gear="0 0 1 0 0 {Quadrotor._SPIN[i] * p.km / p.kf:.6f}" '
                     f'ctrllimited="true" ctrlrange="0 {f_max:.4f}"/>' for i in range(4))
    return f"""
<mujoco model="lucid_phantom2">
  <option timestep="{dt}" gravity="0 0 -{G}" integrator="RK4"/>
  <worldbody>
    <geom name="ground" type="plane" size="500 500 0.1" friction="0.9 0.01 0.001"/>
    <body name="quad" pos="0 0 1.2">
      <freejoint/>
      <inertial pos="0 0 0" mass="{p.mass}" diaginertia="{p.ixx} {p.iyy} {p.izz}"/>
      <geom type="box" size="0.09 0.09 0.04" rgba="0.95 0.95 0.95 1"/>
      {rotors}
      {sites}
    </body>
  </worldbody>
  <actuator>
    {acts}
  </actuator>
</mujoco>"""


class MujocoQuadrotor(Quadrotor):
    """Drop-in replacement for lucid.physics.Quadrotor, integrated by MuJoCo."""

    engine = f"MuJoCo {mujoco.__version__}"

    def __init__(self, params: QuadParams | None = None, altitude: float = 1.2, yaw: float = 0.0, dt: float = 1 / 400):
        p = params or QuadParams()
        self.model = mujoco.MjModel.from_xml_string(build_mjcf(p, dt))
        self.data = mujoco.MjData(self.model)
        self.body = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "quad")
        self.ground = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "ground")
        super().__init__(p, altitude, yaw)

    def reset(self, altitude: float = 1.2, yaw: float = 0.0):
        super().reset(altitude, yaw)
        if not hasattr(self, "data"):
            return
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[:3] = self.pos
        self.data.qpos[3:7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
        mujoco.mj_forward(self.model, self.data)

    def step(self, w_cmd: np.ndarray, dt: float):
        p = self.p
        if abs(self.model.opt.timestep - dt) > 1e-9:
            self.model.opt.timestep = dt
        w_cmd = np.clip(w_cmd, 0.0, p.w_max)
        self.w += (w_cmd - self.w) * min(1.0, dt / p.motor_tau)
        self.data.ctrl[:] = p.kf * self.w ** 2
        v = self.data.qvel[:3]
        self.data.xfrc_applied[self.body, :3] = -p.drag * np.linalg.norm(v) * v  # quadratic drag at the CoM
        v0 = v.copy()
        mujoco.mj_step(self.model, self.data)
        # Read the state back into the shared fields the controller and twin use.
        self.pos = self.data.qpos[:3].copy()
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, self.data.qpos[3:7])
        self.R = R.reshape(3, 3)
        self.vel = self.data.qvel[:3].copy()  # free joint: linear velocity in the world frame
        self.omega = self.data.qvel[3:6].copy()  # angular velocity in the body frame
        self.on_ground = any(
            (c.geom1 == self.ground or c.geom2 == self.ground) for c in self.data.contact[: self.data.ncon]
        )
        T = float((p.kf * self.w ** 2).sum())
        self.energy_wh += p.hover_power_w * max(0.0, T / (p.mass * G)) ** 1.5 * dt / 3600.0
        self.t += dt
        return (self.vel - v0) / dt
