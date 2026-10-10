"""Audit recorded flights for world-model failures, offline (no Reactor credit).

    python scripts/audit_bank.py                       # every recorded flight
    python scripts/audit_bank.py flight-20261010-105539 --series

Writes audit.json next to each episode, and prints the per-chunk signals with --series.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lucid import places  # noqa: E402,F401  (registers uploaded places)
from lucid.audit import WorldAudit  # noqa: E402
from lucid.config import DATA  # noqa: E402
from lucid.prompts import WORLDS  # noqa: E402
from lucid.sentinel import load_detector  # noqa: E402


def audit_episode(ep: Path, detector, series=False) -> dict | None:
    summ = json.loads((ep / "summary.json").read_text(encoding="utf-8"))
    spec = WORLDS.get(summ.get("scene"))
    frames = sorted((ep / "frames").glob("*.jpg"))
    if spec is None or not frames:
        return None
    steps = {}
    if (ep / "steps.jsonl").exists():
        for line in (ep / "steps.jsonl").read_text(encoding="utf-8").splitlines():
            if line:
                s = json.loads(line)
                steps[s["chunk"]] = s
    audit = WorldAudit(spec, detector)
    for f in frames:
        k = int(f.stem)
        if steps.get(k, {}).get("event") or steps.get(k, {}).get("steer"):
            audit.expect_change(k)
        r = audit.update(cv2.cvtColor(cv2.imread(str(f)), cv2.COLOR_BGR2RGB), k)
        if series:
            ev = ",".join(e.kind for e in r.events)
            print(f"  {k:4d} scene {r.scene:.2f} cont {r.continuity if r.continuity is None else round(r.continuity, 2)} "
                  f"colour {r.colour:5.1f} drone {r.drone_match:.2f} {'ok ' if r.trusted else 'BAD'} {ev}")
    out = {"run": summ.get("run"), "scene": summ.get("scene"), "world": summ.get("world"), **audit.summary(),
           "readings": [r.to_dict() for r in audit.readings],
           "events": [{**e.__dict__} for e in audit.log]}
    (ep / "audit.json").write_text(json.dumps(out), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="*")
    ap.add_argument("--series", action="store_true")
    ap.add_argument("--world", default="", help="only flights from this world (reactor | mock)")
    args = ap.parse_args()
    detector = load_detector()
    bank = DATA / "bank"
    runs = [bank / r for r in args.runs] if args.runs else sorted(bank.glob("flight-*"))
    for run in runs:
        for ep in sorted(p for p in run.iterdir() if p.is_dir()):
            if not (ep / "summary.json").exists():
                continue
            if args.world and json.loads((ep / "summary.json").read_text(encoding="utf-8")).get("world") != args.world:
                continue
            print(f"== {run.name}/{ep.name}", flush=True)
            out = audit_episode(ep, detector, args.series)
            if out:
                print(f"   {out['world']} {out['scene']}: {out['chunks']} chunks, trusted {out['trusted_share']:.0%}, "
                      f"events {out['counts']}, first failure at chunk {out['first_failure']}", flush=True)


if __name__ == "__main__":
    main()
