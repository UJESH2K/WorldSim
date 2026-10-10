"""Train the stock ("factory") pilot that the Pilot Lab imports as v0.

It learns by imitation only, and only from easy flights: a sunlit open field, sparse trees,
nothing moving. That is what an off-the-shelf model has seen. The Lab then puts it where it has to
work (warehouse aisles, night, clutter, someone stepping into the path) and improves it from its
own mistakes.

    python scripts/factory_pilot.py --episodes 160
"""
import argparse
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lucid.config import DATA  # noqa: E402
from lucid.lab.env import scenarios  # noqa: E402
from lucid.lab.pilot import INDEX, batch  # noqa: E402
from lucid.lab.train import Trainer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=160)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out", default=str(DATA / "models" / "factory-pilot.pt"))
    args = ap.parse_args()
    torch.manual_seed(7)
    tr = Trainer(None, "factory", workers=args.workers)
    with mp.get_context("spawn").Pool(args.workers) as pool:
        t = time.time()
        eps = tr._fly(pool, tr.pilot.state(), scenarios(args.episodes, seed=77, profile="open-field"), 0.0, 7, beta=1.0)
        samples = [{k: s[k] for k in ("prev", "cur", "active", "expert")} for e in eps for s in e["steps"]]
        print(f"{len(samples)} demonstration states from {len(eps)} open-field flights ({time.time() - t:.0f}s)", flush=True)
        x, a = batch(samples)
        y = torch.tensor([INDEX[s["expert"]] for s in samples])
        net = tr.pilot.net
        opt = torch.optim.Adam(net.parameters(), 1e-3)
        ce = torch.nn.CrossEntropyLoss()
        for epoch in range(args.epochs):
            net.train()
            p = torch.randperm(len(y))
            for i in range(0, len(p), 256):
                b = p[i:i + 256]
                loss = ce(net(x[b], a[b])[0], y[b])
                opt.zero_grad()
                loss.backward()
                opt.step()
            print(f"  epoch {epoch + 1}: loss {loss.item():.3f}", flush=True)
        net.eval()
        rows = {}
        for name, bench in (("open field", scenarios(24, seed=2027, profile="open-field")), ("field", scenarios(24, seed=2026))):
            rows[name] = tr.evaluate(pool, tr.pilot.state(), bench, "factory")["row"]
            print(f"  on {name}: {rows[name]}", flush=True)
    tr.pilot.save(Path(args.out), {"name": "Factory pilot", "trained_on": "open-field daylight flights, sparse, static",
                                   "demonstrations": len(samples), "flights": len(eps), "scores": rows})
    print("saved", args.out)


if __name__ == "__main__":
    main()
