"""The pilot under test: a vision policy, two camera frames + current command -> next command.

Input: the current chase-camera view in colour (96 x 56), contrast-normalised so the same scene
reads alike in daylight and at night, plus the brightness change since the previous decision
(motion: what is getting bigger, how fast the world slides past). A small CNN keeps a 4 x 6 grid
of where things are; two heads read it: the policy (which command next) and the value (expected
future reward from here), which the reinforcement-learning update uses to tell good decisions
from lucky ones.
"""
import cv2
import numpy as np
import torch
from torch import nn

from ..actions import EMBODIMENTS

ACTIONS = EMBODIMENTS["drone"]
INDEX = {a: i for i, a in enumerate(ACTIONS)}
ARCH = "pilot-v2-rgb96"
IN_W, IN_H = 96, 56


def observe(frame: np.ndarray) -> np.ndarray:
    """Full camera frame (RGB) -> what the pilot sees."""
    return cv2.resize(frame, (IN_W, IN_H), interpolation=cv2.INTER_AREA)


def gray(view: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(view, cv2.COLOR_RGB2GRAY)


def stack(prev_gray: np.ndarray, cur: np.ndarray) -> np.ndarray:
    c = cur.astype(np.float32) / 255.0
    m, s = float(c.mean()), float(c.std()) + 0.05
    d = (c.mean(2) - prev_gray.astype(np.float32) / 255.0) / s * 2.0
    return np.concatenate([((c - m) / s).transpose(2, 0, 1), d[None]], 0)


class PilotNet(nn.Module):
    def __init__(self, n_actions: int = len(ACTIONS)):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(4, 32, 5, 2, 2), nn.ReLU(),
            nn.Conv2d(32, 64, 3, 2, 1), nn.ReLU(),
            nn.Conv2d(64, 64, 3, 2, 1), nn.ReLU(),
            nn.Conv2d(64, 64, 3, 1, 1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 6)),
        )
        n = 64 * 24 + n_actions
        self.head = nn.Sequential(nn.Linear(n, 128), nn.ReLU(), nn.Linear(128, n_actions))
        self.value = nn.Sequential(nn.Linear(n, 128), nn.ReLU(), nn.Linear(128, 1))

    def forward(self, frames, active):
        z = torch.cat([self.conv(frames).flatten(1), active], dim=1)
        return self.head(z), self.value(z).squeeze(1)


def encode(prev_gray, cur, active: str):
    x = torch.from_numpy(stack(prev_gray, cur))[None]
    a = torch.zeros(1, len(ACTIONS))
    a[0, INDEX.get(active, 0)] = 1.0
    return x, a


def batch(samples):
    x = torch.from_numpy(np.stack([stack(s["prev"], s["cur"]) for s in samples]))
    a = nn.functional.one_hot(torch.tensor([INDEX[s["active"]] for s in samples]), len(ACTIONS)).float()
    return x, a


class Pilot:
    def __init__(self, net: PilotNet | None = None, meta: dict | None = None):
        self.net = net or PilotNet()
        self.net.eval()
        self.meta = meta or {}

    @classmethod
    def load(cls, path) -> "Pilot":
        """A pilot checkpoint (weights + action list). The value head may be missing (pure imitation pilots)."""
        blob = torch.load(path, weights_only=True, map_location="cpu")
        state = blob.get("state", blob) if isinstance(blob, dict) else blob
        if blob.get("arch", ARCH) != ARCH:
            raise ValueError(f"this pilot is a {blob.get('arch')} network; the Lab flies {ARCH}")
        net = PilotNet()
        try:
            missing, unexpected = net.load_state_dict(state, strict=False)
        except RuntimeError:  # shape mismatch: say which, in terms a person can act on
            mine = net.state_dict()
            bad = next((k for k, v in state.items() if k in mine and tuple(v.shape) != tuple(mine[k].shape)), None)
            what = (f"layer {bad} is {tuple(state[bad].shape)}, the Lab's is {tuple(mine[bad].shape)}" if bad else "layer shapes differ")
            raise ValueError(f"the Lab flies {ARCH}: 4 input channels (colour + motion) at {IN_W}x{IN_H}, "
                             f"{len(ACTIONS)} commands; {what}") from None
        if unexpected or any(not k.startswith("value.") for k in missing):
            raise ValueError(f"not a compatible pilot: missing {missing[:3]}, unexpected {unexpected[:3]}")
        return cls(net, blob.get("meta", {}))

    def save(self, path, meta: dict | None = None):
        torch.save({"state": self.net.state_dict(), "arch": ARCH, "actions": ACTIONS, "meta": meta or {}}, path)

    def state(self) -> dict:
        return {k: v.clone() for k, v in self.net.state_dict().items()}

    @torch.no_grad()
    def act(self, prev_gray, cur, active: str, temperature: float = 0.0, rng=None) -> str:
        x, a = encode(prev_gray, cur, active)
        logits, _ = self.net(x, a)
        if temperature <= 0:
            return ACTIONS[int(logits.argmax())]
        p = torch.softmax(logits[0] / temperature, 0).numpy().astype(np.float64)
        return ACTIONS[int((rng or np.random).choice(len(p), p=p / p.sum()))]
