"""The student: a small CNN that maps two consecutive frames to an action in ~1 ms on CPU.

It sees raw pixels only. The teacher sees optical flow geometry (or, with the Claude
teacher, semantic judgement), so the student is distilling a slower, privileged expert into
a reflex that could run on a drone's flight computer.
"""
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn

from .actions import EMBODIMENTS

IN_W, IN_H = 80, 48


def shrink(gray: np.ndarray) -> np.ndarray:
    return cv2.resize(gray, (IN_W, IN_H), interpolation=cv2.INTER_AREA)


class StudentNet(nn.Module):
    def __init__(self, n_actions: int):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(3, 16, 5, 2, 2), nn.ReLU(),
            nn.Conv2d(16, 32, 3, 2, 1), nn.ReLU(),
            nn.Conv2d(32, 32, 3, 2, 1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((3, 5)),
        )
        self.head = nn.Sequential(nn.Linear(32 * 15 + n_actions, 64), nn.ReLU(), nn.Linear(64, n_actions))

    def forward(self, frames, active):
        return self.head(torch.cat([self.conv(frames).flatten(1), active], dim=1))


def _stack(prev: np.ndarray, cur: np.ndarray) -> np.ndarray:
    p, c = prev.astype(np.float32) / 255.0, cur.astype(np.float32) / 255.0
    return np.stack([p, c, (c - p) * 4.0])


class Dataset:
    """Aggregated (state, teacher label) pairs: the D in DAgger."""

    def __init__(self):
        self.prev, self.cur, self.active, self.label = [], [], [], []
        self.rejected = 0

    def __len__(self):
        return len(self.label)

    def add(self, prev, cur, active: int, label: int):
        self.prev.append(shrink(prev))
        self.cur.append(shrink(cur))
        self.active.append(active)
        self.label.append(label)

    def tensors(self, n_actions: int):
        x = torch.from_numpy(np.stack([_stack(p, c) for p, c in zip(self.prev, self.cur)]))
        a = torch.nn.functional.one_hot(torch.tensor(self.active), n_actions).float()
        y = torch.tensor(self.label)
        return x, a, y


class Student:
    # balance=0.5 (sqrt weights): full balancing made the student over-predict rare evasive
    # turns and fly in circles (val acc 0.51 vs 0.82 on the mock sweep).
    def __init__(self, embodiment: str = "drone", seed: int = 0, balance: float = 0.5):
        torch.manual_seed(seed)
        self.balance = balance
        self.actions = EMBODIMENTS[embodiment]
        self.index = {a: i for i, a in enumerate(self.actions)}
        self.net = StudentNet(len(self.actions))
        self.trained = False

    def one_hot(self, action: str) -> torch.Tensor:
        v = torch.zeros(1, len(self.actions))
        v[0, self.index.get(action, 0)] = 1.0
        return v

    @torch.no_grad()
    def act(self, prev: np.ndarray, cur: np.ndarray, active: str) -> tuple[str, list[float]]:
        self.net.eval()
        x = torch.from_numpy(_stack(shrink(prev), shrink(cur)))[None]
        probs = torch.softmax(self.net(x, self.one_hot(active)), dim=1)[0]
        return self.actions[int(probs.argmax())], [round(float(p), 3) for p in probs]

    def fit(self, data: Dataset, epochs: int = 12, lr: float = 2e-3, batch: int = 64) -> dict:
        n = len(self.actions)
        x, a, y = data.tensors(n)
        perm = torch.randperm(len(y))
        split = max(1, int(len(y) * 0.85))
        tr, va = perm[:split], perm[split:]
        counts = torch.bincount(y[tr], minlength=n).float()
        # Inverse-frequency class weights raised to `balance`: 1 = fully balanced, 0 = none.
        weights = ((counts.sum() / (counts + 1.0)) / n) ** self.balance
        loss_fn = nn.CrossEntropyLoss(weight=weights.clamp(max=20.0))
        opt = torch.optim.Adam(self.net.parameters(), lr=lr)
        self.net.train()
        for _ in range(epochs):
            tr = tr[torch.randperm(len(tr))]
            for i in range(0, len(tr), batch):
                idx = tr[i:i + batch]
                loss = loss_fn(self.net(x[idx], a[idx]), y[idx])
                opt.zero_grad()
                loss.backward()
                opt.step()
        self.trained = True
        self.net.eval()
        with torch.no_grad():
            train_acc = float((self.net(x[tr], a[tr]).argmax(1) == y[tr]).float().mean())
            val_acc = float((self.net(x[va], a[va]).argmax(1) == y[va]).float().mean()) if len(va) else None
        return {"samples": len(y), "train_acc": round(train_acc, 3),
                "val_acc": round(val_acc, 3) if val_acc is not None else None}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"actions": self.actions, "state": self.net.state_dict()}, path)

    def load(self, path: Path) -> None:
        blob = torch.load(path, weights_only=True)
        self.net.load_state_dict(blob["state"])
        self.trained = True
