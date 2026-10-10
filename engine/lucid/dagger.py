"""Recursive training (DAgger, Ross et al. 2011) inside the world.

Behaviour cloning alone fails because the student drifts into states the teacher never
visited. DAgger fixes that by letting the student drive, having the teacher label the
states the *student* reached, aggregating, and retraining:

    round 0   teacher drives                       -> D0
    round i   student drives (teacher w.p. beta_i) -> teacher relabels -> D += Di -> retrain

A world model is what makes this affordable: the student's own mistakes, in fog, at night,
with a worker stepping into the aisle, become training data without a real crash.
States where the world ignored the control (low obedience) are rejected, never trained on.
"""
import asyncio
import time

import numpy as np

from .bank import EpisodeRecorder
from .budget import BudgetExceeded
from .config import DATA
from .loop import Telemetry, run_episode
from .policy import Dataset, Student
from .scenarios import sample_scenes
from .teacher import ReflexTeacher


def _pct(rate) -> str:
    return "n/a" if rate is None else f"{rate:.0%}"


async def evaluate(world, scenes, teacher, student, max_chunks, telemetry, rng, who: str) -> dict:
    results = []
    for scene in scenes:
        if telemetry.stop_requested:
            break
        telemetry.detail = f"eval {who} on {scene.name}"
        s = await run_episode(world, scene, teacher, student=student if who == "student" else None,
                              beta=0.0 if who == "student" else 1.0, max_chunks=max_chunks, rng=rng,
                              telemetry=telemetry)
        results.append(s)
    n = max(1, len(results))
    known = all(r["collided"] is not None for r in results)  # LingBot has no ground truth
    return {
        "who": who,
        "episodes": len(results),
        "collision_rate": round(sum(r["collided"] for r in results) / n, 3) if known else None,
        "mean_chunks": round(float(np.mean([r["chunks"] for r in results])) if results else 0, 1),
        "agreement": round(float(np.mean([r["agreement"] for r in results])) if results else 0, 3),
        # Progress guards against the degenerate safe policy (spin in place, never crash).
        "mean_distance_m": round(float(np.mean([r.get("distance_m") or 0 for r in results])), 2) if results else 0,
    }


async def train(world, telemetry: Telemetry, *, embodiment="drone", rounds=4, episodes_per_round=6,
                eval_episodes=6, max_chunks=40, seed=0, record=True, obedience_min=0.3) -> dict:
    run_id = time.strftime("run-%Y%m%d-%H%M%S")
    rng = np.random.default_rng(seed)
    teacher = ReflexTeacher(embodiment)
    student = Student(embodiment, seed=seed)
    data = Dataset()
    eval_scenes = sample_scenes(eval_episodes, seed=seed + 999, max_chunks=max_chunks)
    telemetry.rounds = []
    telemetry.say(f"{run_id}: DAgger x{rounds} rounds, {episodes_per_round} eps/round on {world.kind}")

    baseline = await evaluate(world, eval_scenes, teacher, None, max_chunks, telemetry, rng, "teacher")
    telemetry.say(f"teacher baseline: collisions {_pct(baseline['collision_rate'])}, "
                  f"survives {baseline['mean_chunks']} chunks")

    out_of_time = False  # a capped world-model session ends collection, not the training
    for r in range(rounds):
        if telemetry.stop_requested:
            break
        beta = 1.0 if r == 0 else 0.5 ** r
        scenes = sample_scenes(episodes_per_round, seed=seed + r * 101, max_chunks=max_chunks)
        collected = {"labelled": 0, "rejected": 0, "collisions": 0}
        try:
            for e, scene in enumerate(scenes):
                if telemetry.stop_requested:
                    break
                telemetry.detail = f"round {r} (beta {beta:.2f}) ep {e + 1}/{len(scenes)}: {scene.name}"
                samples = []
                rec = EpisodeRecorder(run_id, r * 100 + e, scene.name, world.kind) if record else None
                s = await run_episode(world, scene, teacher, student=student, beta=beta, max_chunks=max_chunks,
                                      rng=rng, recorder=rec, telemetry=telemetry, samples=samples,
                                      obedience_min=obedience_min)
                for prev, cur, active, label in samples:
                    data.add(prev, cur, student.index.get(active, 0), student.index[label])
                collected["labelled"] += s["labelled"]
                collected["rejected"] += s["rejected"]
                collected["collisions"] += bool(s["collided"])
                telemetry.episodes.append({"round": r, **s})
        except BudgetExceeded as exc:
            telemetry.say(f"{exc}; training on what was collected")
            out_of_time = True
        if len(data) == 0:
            break

        telemetry.detail = f"round {r}: training student on {len(data)} states"
        fit = await asyncio.to_thread(student.fit, data)  # keep the dashboard responsive meanwhile
        ev = {"who": "student", "episodes": 0, "collision_rate": None, "mean_chunks": 0,
              "agreement": 0, "mean_distance_m": 0}
        if not out_of_time:
            try:
                ev = await evaluate(world, eval_scenes, teacher, student, max_chunks, telemetry, rng, "student")
            except BudgetExceeded as exc:
                telemetry.say(f"{exc}; skipping evaluation")
                out_of_time = True
        row = {"round": r, "beta": round(beta, 3), **collected, "dataset": len(data), **fit,
               "eval": ev, "teacher_eval": baseline}
        telemetry.rounds.append(row)
        telemetry.say(f"round {r}: D={len(data)} val_acc={fit['val_acc']} | student collisions "
                      f"{_pct(ev['collision_rate'])} survives {ev['mean_chunks']} chunks, "
                      f"rejected {collected['rejected']} disobeyed states")
        if out_of_time:
            break

    path = DATA / "models" / f"{run_id}.pt"
    student.save(path)
    telemetry.say(f"saved student -> {path.relative_to(DATA.parent)}")
    return {"run": run_id, "rounds": telemetry.rounds, "baseline": baseline, "model": str(path)}
