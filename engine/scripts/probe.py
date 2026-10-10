"""The gate: does LingBot World 2 obey the controls, and how fast is the loop?

One short session, hard-capped. Drives a scripted action sequence from the forest seed and
measures, per action, whether the optical flow of the generated video matches the command
(obedience), plus chunk rate and command-to-effect latency in chunks.

    python scripts/probe.py --seconds 90
"""
import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lucid import budget  # noqa: E402
from lucid.bank import EpisodeRecorder  # noqa: E402
from lucid.config import DATA  # noqa: E402
from lucid.perception import perceive, prep  # noqa: E402
from lucid.scenarios import make_scene  # noqa: E402
from lucid.worlds.reactor_world import ReactorWorld  # noqa: E402

SCRIPT = ([("hover", 3), ("forward", 8), ("yaw_left", 5), ("forward", 3), ("yaw_right", 5),
           ("arc_left", 5), ("back", 5), ("up", 5), ("down", 4), ("hover", 3)])


async def main(seconds: int, wall_cap: float):
    print("budget before:", json.dumps({k: v for k, v in budget.summary().items() if k != "sessions"}))
    world = ReactorWorld("drone")
    run_id = time.strftime("probe-%Y%m%d-%H%M%S")
    rec = EpisodeRecorder(run_id, 0, "forest-probe", "reactor")
    report = {"run": run_id, "steps": []}
    per_action = defaultdict(list)
    latencies = []
    try:
        await world.open(planned_seconds=seconds)
        t_open = time.monotonic()
        await world.start(make_scene("forest", "clear", seed=42))
        prev = None
        plan = [a for a, n in SCRIPT for _ in range(n)]
        sent_at = {}  # action -> chunk index when it was sent
        t_first = None
        for i, action in enumerate(plan + ["hover"] * 2):
            if time.monotonic() - t_open > wall_cap:
                print("wall-clock cap reached, stopping")
                break
            chunk = await world.next_chunk()
            t_first = t_first or time.monotonic()
            cur = prep(chunk.frames[-1])
            p = perceive(prev, cur, chunk.action) if prev is not None else None
            if p is not None:
                per_action[chunk.action].append(p.obedience)
            if chunk.action in sent_at:
                latencies.append(chunk.index - sent_at.pop(chunk.action))
            step = {"chunk": chunk.index, "sent": world.sent_action, "active": chunk.action,
                    "raw_active": chunk.raw_action, "perception": p.to_dict() if p else None,
                    "truth": chunk.info}
            report["steps"].append(step)
            rec.add(step, cur, chunk.frames[-1], extra_frames=chunk.frames[:-1])
            print(f"chunk {chunk.index:3d} active={chunk.raw_action!s:10s}->{chunk.action:9s} "
                  f"frames={chunk.info['frames_received']:3d} "
                  + (f"obey={p.obedience:+.2f} sx={p.sx:+.3f} sy={p.sy:+.3f} u={p.u:+.3f} v={p.v:+.3f} coh={p.coherence:.2f}" if p else ""))
            prev = cur
            if i < len(plan):
                nxt = plan[i]
                if nxt != world.sent_action:
                    sent_at[nxt] = chunk.index
                await world.act(nxt)
        n_chunks = len(report["steps"])
        dur = time.monotonic() - (t_first or time.monotonic())
        report["chunks_per_s"] = round((n_chunks - 1) / dur, 2) if dur > 0 else None
        report["frames_per_s"] = round(world.frames_total / max(1e-6, world.elapsed()), 1)
        report["latency_chunks"] = latencies
        report["obedience"] = {a: round(sum(v) / len(v), 3) for a, v in per_action.items() if v}
        report["errors"] = list(world.errors)
    finally:
        await world.close()
        rec.close({"probe": True})
        report["usage"] = world.usage()
        out = DATA / "probes" / f"{run_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("\n=== PROBE REPORT ===")
        for k in ("chunks_per_s", "frames_per_s", "latency_chunks", "obedience", "errors", "usage"):
            print(f"{k}: {report.get(k)}")
        print("frames saved under", rec.dir)
        print("budget after:", json.dumps({k: v for k, v in budget.summary().items() if k != "sessions"}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=90, help="hard session cap (billed at most this long)")
    ap.add_argument("--wall-cap", type=float, default=75.0, help="stop driving after this many seconds")
    args = ap.parse_args()
    asyncio.run(main(args.seconds, args.wall_cap))
