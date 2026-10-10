"""One Pilot Lab run as its own process (the server starts it; CPU-heavy, so it never shares the
event loop with a live flight).

    python -m lucid.lab.run --run lab-20261010-120801 --base data/models/factory-pilot.pt

Writes data/lab/<run>/progress.json as it goes and run.json after every iteration; stops early
(and still compares v0 with the best version) when data/lab/<run>/STOP appears.
"""
import argparse
import json
import time
import traceback
from pathlib import Path

from .train import LAB, Trainer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--episodes", type=int, default=48)
    ap.add_argument("--bench", type=int, default=32)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    folder = LAB / args.run
    folder.mkdir(parents=True, exist_ok=True)
    state = {"run": args.run, "status": "running", "stage": "Loading the pilot", "iteration": 0,
             "iterations": args.iterations, "episodes": args.episodes, "bench": args.bench,
             "base": Path(args.base).name, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "log": []}

    def write():
        state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tmp = folder / "progress.json.tmp"
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(folder / "progress.json")

    def progress(**k):
        if "stage" in k:
            state["stage"] = k["stage"]
            state["log"] = (state["log"] + [f"{time.strftime('%H:%M:%S')}  {k['stage']}"])[-40:]
        if "iteration" in k:
            state["iteration"] = k["iteration"]
        if "rows" in k:
            state["rows"] = k["rows"]
        write()

    write()
    try:
        out = Trainer(Path(args.base), args.run, progress, workers=args.workers).run(
            args.iterations, args.episodes, args.bench, stop=lambda: (folder / "STOP").exists())
        state.update(status="stopped" if (folder / "STOP").exists() else "done", stage="Finished",
                     best=out["final"]["best"])
    except Exception as e:  # noqa: BLE001 - the dashboard shows it
        state.update(status="error", stage=f"error: {e!r}", trace=traceback.format_exc()[-2000:])
    write()


if __name__ == "__main__":
    main()
