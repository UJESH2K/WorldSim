"""Learnability check for the Pilot Lab: can the vision pilot learn the expert from pixels at all?

    python scripts/lab_diag.py --episodes 240
"""
import argparse
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lucid.lab.env import scenarios  # noqa: E402
from lucid.lab.pilot import INDEX  # noqa: E402
from lucid.lab.pilot import batch  # noqa: E402
from lucid.lab.train import Trainer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="")
    ap.add_argument("--episodes", type=int, default=240)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    tr = Trainer(Path(args.base) if args.base else None, "diag", workers=args.workers)
    bench = scenarios(24, seed=2026)
    with mp.get_context("spawn").Pool(args.workers) as pool:
        t = time.time()
        exp = tr._fly(pool, tr.pilot.state(), bench, 0.0, 0, beta=1.0, keep_steps=False)
        print(f"expert on benchmark: crash {sum(e['crashed'] for e in exp)}/24, distance "
              f"{np.mean([e['distance'] for e in exp]):.1f} m ({time.time() - t:.0f}s)", flush=True)
        t = time.time()
        data = tr._fly(pool, tr.pilot.state(), scenarios(args.episodes, seed=555), 0.0, 1, beta=1.0)
        samples = [{k: s[k] for k in ("prev", "cur", "active", "expert")} for e in data for s in e["steps"]]
        print(f"collected {len(samples)} expert-flown states in {time.time() - t:.0f}s", flush=True)
        x, a = batch(samples)
        y = torch.tensor([INDEX[s["expert"]] for s in samples])
        print("label mix:", {k: round(float((y == INDEX[k]).float().mean()), 2) for k in
                             ["forward", "arc_left", "arc_right", "yaw_left", "yaw_right", "hover", "back"]}, flush=True)
        net = tr.pilot.net
        opt = torch.optim.Adam(net.parameters(), 1e-3)
        ce = torch.nn.CrossEntropyLoss()
        perm = torch.randperm(len(y))
        split = int(len(y) * 0.9)
        trn, val = perm[:split], perm[split:]
        for epoch in range(args.epochs):
            net.train()
            p = trn[torch.randperm(len(trn))]
            for i in range(0, len(p), 256):
                b = p[i:i + 256]
                lo, _ = net(x[b], a[b])
                loss = ce(lo, y[b])
                opt.zero_grad()
                loss.backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                acc = (net(x[val], a[val])[0].argmax(1) == y[val]).float().mean().item()
            print(f"  epoch {epoch + 1}: held-out agreement {acc:.2f}", flush=True)
        ev = tr.evaluate(pool, tr.pilot.state(), bench, "bc")
        print("pilot after pure imitation:", ev["row"], flush=True)
        tr.pilot.save(Path("data/lab/diag-bc.pt"))


if __name__ == "__main__":
    main()
