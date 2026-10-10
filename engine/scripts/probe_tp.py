"""Gate for the third-person drone: does LingBot keep the drone centred and obey WASD?

Drives a scripted sequence from a drone-in-scene seed with layered prompts, then reports
per-action obedience (flow measured around the masked drone), whether the drone is still
the drone (correlation with the seed's drone patch), and fires one live event.

    python scripts/probe_tp.py --world forest --seconds 60
"""
import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lucid import budget  # noqa: E402
from lucid.bank import EpisodeRecorder  # noqa: E402
from lucid.config import ASSETS, DATA  # noqa: E402
from lucid.perception import perceive, prep, subject_presence  # noqa: E402
from lucid.prompts import WORLDS  # noqa: E402
from lucid.worlds.base import Scene  # noqa: E402
from lucid.worlds.reactor_world import ReactorWorld  # noqa: E402

SCRIPT = [("hover", 3), ("forward", 8), ("arc_left", 5), ("forward", 3), ("yaw_right", 5),
          ("forward", 6), ("back", 4), ("hover", 3)]
EVENT_AT = 22  # chunk index for "worker steps in"


async def main(world_key: str, seconds: int):
    spec = WORLDS[world_key]
    box, mask = spec.drone_box, spec.flow_mask
    seed_gray = cv2.cvtColor(cv2.imread(str(ASSETS / "seeds" / spec.image)), cv2.COLOR_BGR2GRAY)
    world = ReactorWorld("drone")
    run_id = time.strftime(f"tp-{world_key}-%Y%m%d-%H%M%S")
    rec = EpisodeRecorder(run_id, 0, world_key, "reactor")
    per_action, presence, rows = defaultdict(list), [], []
    try:
        await world.open(planned_seconds=seconds)
        await world.start(Scene(name=world_key, prompt="", seed=7, world_key=world_key))
        plan = [a for a, n in SCRIPT for _ in range(n)]
        prev = None
        for i, action in enumerate(plan + ["hover"] * 2):
            if i == EVENT_AT:
                await world.steer("worker steps in")
            chunk = await world.next_chunk()
            frame = chunk.frames[-1]
            cur = prep(frame)
            p = perceive(prev, cur, chunk.action, mask=mask) if prev is not None else None
            pres = subject_presence(seed_gray, cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), box)
            presence.append(pres)
            if p is not None:
                per_action[chunk.action].append(p.obedience)
            step = {"chunk": chunk.index, "sent": world.sent_action, "active": chunk.action,
                    "perception": p.to_dict() if p else None, "presence": round(pres, 3), "truth": chunk.info}
            rows.append(step)
            rec.add(step, cur, frame)
            print(f"chunk {chunk.index:3d} {chunk.action:9s} presence={pres:+.2f} "
                  + (f"obey={p.obedience:+.2f} danger={p.danger:.2f}" if p else ""), flush=True)
            prev = cur
            if i < len(plan):
                await world.act(plan[i])
    except budget.BudgetExceeded as e:
        print("stopped:", e)
    finally:
        await world.close()
        rec.close({"probe": "third-person"})
        report = {
            "run": run_id,
            "obedience": {a: round(float(np.mean(v)), 3) for a, v in per_action.items()},
            "presence_mean": round(float(np.mean(presence)), 3) if presence else None,
            "presence_min": round(float(np.min(presence)), 3) if presence else None,
            "usage": world.usage(),
            "steps": rows,
        }
        out = DATA / "probes" / f"{run_id}.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("\n=== THIRD-PERSON PROBE ===")
        for k in ("obedience", "presence_mean", "presence_min", "usage"):
            print(f"{k}: {report[k]}")
        print("frames:", rec.dir)
        print("budget:", {k: v for k, v in budget.summary().items() if k != "sessions"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="forest", choices=list(WORLDS))
    ap.add_argument("--seconds", type=int, default=60)
    args = ap.parse_args()
    asyncio.run(main(args.world, args.seconds))
