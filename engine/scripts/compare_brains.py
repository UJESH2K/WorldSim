"""Hand-tuned autopilot vs the Pilot Lab's learned pilot, in the product's own flight loop
(practice world, MuJoCo twin, Sentinel on), same seeds. Free.

    python scripts/compare_brains.py --flights 12 --model lab-lab-20261010-124141-v7.pt
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lucid.config import DATA  # noqa: E402
from lucid.flight import FlightState, fly  # noqa: E402
from lucid.lab.pilot import Pilot  # noqa: E402
from lucid.loop import Telemetry  # noqa: E402
from lucid.prompts import WORLDS  # noqa: E402
from lucid.sentinel import Sentinel  # noqa: E402
from lucid.worlds.mock import MockWorld  # noqa: E402


async def run(brain: str, net, flights: int, chunks: int) -> list[dict]:
    out = []
    sentinels = {k: Sentinel(WORLDS[k], kind="mock") for k in ("forest", "warehouse")}
    for i in range(flights):
        scene = ("forest", "warehouse")[i % 2]
        fs = FlightState()
        fs.brain, fs.learned = brain, ("lab", net) if net else None
        world = MockWorld("drone", realtime=False, size=(384, 216))
        s = await fly(world, scene, fs, Telemetry(), max_chunks=chunks, seed=500 + i, record=False, narrate=False,
                      sentinel=sentinels[scene])
        out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flights", type=int, default=12)
    ap.add_argument("--chunks", type=int, default=40)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    models = DATA / "models"
    path = models / args.model if args.model else sorted(models.glob("lab-*.pt"), key=lambda f: f.stat().st_mtime)[-1]
    net = Pilot.load(path)
    for brain in ("reflex", "learned"):
        t = time.time()
        res = asyncio.run(run(brain, net if brain == "learned" else None, args.flights, args.chunks))
        crash = np.mean([r["crashed_truth"] for r in res])
        print(f"{brain:8s} ({path.name if brain == 'learned' else 'hand-tuned'}): crashes {crash:.0%} "
              f"({sum(r['crashed_truth'] for r in res)}/{len(res)}), distance {np.mean([r['distance_m'] for r in res]):.1f} m, "
              f"referee warnings {np.mean([r['warning'] for r in res]):.1f}/flight ({time.time() - t:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
