"""Teachers label states with the action an expert would take there.

The reflex teacher is model-free obstacle avoidance from optical flow, after the insect
looming and centering responses: veer away from whatever is expanding in the centre of
view, and steer toward the side whose flow is slower (farther away). It is stateless on
purpose: in DAgger, the label must be a function of what the robot observed, so the
student can learn it.
"""
from .actions import EMBODIMENTS
from .perception import TRANSLATING, Perception


class ReflexTeacher:
    name = "reflex"

    def __init__(self, embodiment: str = "drone", veer: float = 0.2, spin: float = 0.45,
                 balance: float = 0.3):
        self.actions = EMBODIMENTS[embodiment]
        self.veer, self.spin, self.balance = veer, spin, balance

    def label(self, p: Perception | None, active: str) -> tuple[str, str]:
        if p is None:
            return "forward", "no flow yet: move to sense depth"
        if active in ("yaw_left", "yaw_right"):
            # Spinning on the spot gives depth-free flow, so keep turning while translating.
            return ("arc_left" if active == "yaw_left" else "arc_right"), "re-sensing depth after spin"
        if active not in TRANSLATING:
            return "forward", "probing: depth needs forward motion"
        freer_left = p.left_flow < p.right_flow
        if p.danger > self.spin:
            return ("yaw_left" if freer_left else "yaw_right"), f"looming {p.danger:.2f}: spin away"
        if p.danger > self.veer:
            return ("arc_left" if freer_left else "arc_right"), f"looming {p.danger:.2f}: veer"
        imbalance = (p.left_flow - p.right_flow) / (p.left_flow + p.right_flow + 1e-6)
        if imbalance > self.balance:
            return "arc_right", "left side closer: centring"
        if imbalance < -self.balance:
            return "arc_left", "right side closer: centring"
        return "forward", "clear"
