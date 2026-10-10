"""Run the Pilot Lab from the command line.

    python scripts/lab_run.py --base data/models/factory-pilot.pt --iterations 10
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lucid.lab.train import Trainer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="data/models/factory-pilot.pt")
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--episodes", type=int, default=48)
    ap.add_argument("--bench", type=int, default=32)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    run_id = time.strftime("lab-%Y%m%d-%H%M%S")

    def progress(**k):
        if "stage" in k:
            print(f"[{time.strftime('%H:%M:%S')}] {k['stage']}", flush=True)
        if "rows" in k:
            r = k["rows"][-1]
            print(f"    {r['version']:>4}: crash {r['crash_rate']:.0%}  distance {r['mean_distance_m']} m  near-miss steps "
                  f"{r['near_miss_steps']}  expert agreement {r['expert_agreement']:.0%}"
                  + (f"  | trained on {r['states']} states, {r['mistakes']} episodes with mistakes" if "states" in r else ""), flush=True)

    out = Trainer(Path(args.base), run_id, progress, workers=args.workers).run(args.iterations, args.episodes, args.bench)
    fixed = out["final"]["fixed"]
    print(f"\nbest: {out['final']['best']} | v0 mistakes fixed: {sum(m['fixed'] for m in fixed)}/{len(fixed)} | replays {out['final']['replays']}")
    print("run folder:", Path("data/lab") / run_id)


if __name__ == "__main__":
    main()
