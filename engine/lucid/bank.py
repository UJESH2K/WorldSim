"""The dream bank: every chunk the world model renders is written to disk once.

World-model GPU time is the scarce resource, so nothing it produces is thrown away. Teacher
relabelling, student training and evaluation of new teachers all replay from here for free.
"""
import json
import time
from pathlib import Path

import cv2
import numpy as np

from .config import DATA

BANK = DATA / "bank"


class EpisodeRecorder:
    def __init__(self, run_id: str, episode: int, scene_name: str, world_kind: str):
        self.dir = BANK / run_id / f"ep{episode:03d}_{scene_name}"
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        self.meta = {"run": run_id, "episode": episode, "scene": scene_name, "world": world_kind,
                     "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.gray = []
        self.steps = self.dir / "steps.jsonl"
        self.steps.write_text("", encoding="utf-8")

    def add(self, step: dict, gray: np.ndarray, rgb: np.ndarray, extra_frames: list | None = None) -> None:
        k = step["chunk"]
        self.gray.append(gray)
        cv2.imwrite(str(self.dir / "frames" / f"{k:04d}.jpg"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 85])
        for j, f in enumerate(extra_frames or []):
            cv2.imwrite(str(self.dir / "frames" / f"{k:04d}_{j:02d}.jpg"), cv2.cvtColor(f, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 80])
        with self.steps.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(step) + "\n")

    def save_audit(self, audit: dict) -> None:
        (self.dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    def close(self, summary: dict) -> None:
        if self.gray:
            np.savez_compressed(self.dir / "gray.npz", gray=np.stack(self.gray))
        (self.dir / "summary.json").write_text(json.dumps({**self.meta, **summary}, indent=2), encoding="utf-8")


def load_episode(path: Path):
    steps = [json.loads(line) for line in (path / "steps.jsonl").read_text(encoding="utf-8").splitlines() if line]
    gray = np.load(path / "gray.npz")["gray"] if (path / "gray.npz").exists() else None
    return steps, gray
