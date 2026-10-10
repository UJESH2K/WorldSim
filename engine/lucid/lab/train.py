"""Recursive improvement: the pilot flies, its mistakes become training data, its weights get better.

Each iteration
    1. roll out   the current pilot on fresh training scenarios (parallel, with exploration)
    2. mistakes   every crash and near miss, plus the steps that led up to it
    3. relabel    every visited state with the privileged expert's choice (DAgger), the steps
                  before a mistake weighted 3x: the pilot learns most where it failed
    4. RL update  advantage-weighted regression (Peng et al. 2019): decisions that beat the
                  value network's expectation are reinforced, a value head learns the return
    5. re-score   on a fixed held-out benchmark it never trains on; the weights are saved as vN
Then replays of the same scenarios with the first and the best version, and a check of whether
each of the first version's mistakes is fixed.
"""
import base64
import json
import multiprocessing as mp
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn

from ..config import DATA
from .env import MAX_STEPS, NEAR, LabEnv, scenarios
from .pilot import ACTIONS, ARCH, INDEX, Pilot, PilotNet, batch

LAB = DATA / "lab"
GAMMA = 0.9
MISTAKE_WINDOW = 6  # steps before a crash / near miss that get extra weight
MISTAKE_WEIGHT = 3.0


def _b64(img, width=320) -> str:
    h = int(width * img.shape[0] / img.shape[1])
    small = cv2.resize(img, (width, h), interpolation=cv2.INTER_LINEAR)
    return base64.b64encode(cv2.imencode(".jpg", cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()).decode()


def rollout_worker(job: dict) -> list[dict]:
    """Fly a list of scenarios with one set of weights. Runs in a separate process."""
    torch.set_num_threads(1)
    net = PilotNet()
    net.load_state_dict(job["state"])
    pilot = Pilot(net)
    rng = np.random.default_rng(job["seed"])
    out = []
    for sc in job["scenarios"]:
        env = LabEnv(sc, size=tuple(job.get("size", (192, 108))))
        prev, cur, active = env.reset()
        steps, done, info, frames = [], False, {}, []
        while not done:
            expert = env.expert_action()
            # DAgger mixing: with probability beta the expert flies, so weak pilots still reach
            # the later, harder parts of a scenario; the pilot's own choice is recorded either way.
            own = pilot.act(prev, cur, active, temperature=job["temperature"], rng=rng)
            a = expert if rng.random() < job.get("beta", 0.0) else own
            s = {"prev": prev, "cur": cur, "active": active, "action": a, "expert": expert, "own": own}
            (prev, cur, active), r, done, info = env.step(a)
            s.update(reward=float(r), clearance=info["clearance"], collided=info["collided"])
            steps.append(s)
            if job.get("thumbs"):
                frames.append(_b64(env.frame))
            if job.get("record_dir"):
                d = Path(job["record_dir"]) / sc["id"]
                d.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(d / f"{env.k:03d}.jpg"), cv2.cvtColor(env.frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
        ep = {"scenario": sc, "steps": steps if job.get("keep_steps", True) else [], "crashed": bool(info.get("collided")),
              "distance": float(info.get("distance", 0.0)), "near": int(sum(s["clearance"] < NEAR for s in steps)),
              "min_clearance": float(min(s["clearance"] for s in steps)), "length": len(steps),
              "agreement": float(np.mean([s["action"] == s["expert"] for s in steps])),
              "trace": [{"a": s["action"], "e": s["expert"], "c": round(s["clearance"], 2)} for s in steps]}
        if job.get("thumbs"):
            ep["mistakes"] = _mistakes(steps, frames, sc)
        out.append(ep)
    return out


def _mistakes(steps, frames, sc) -> list[dict]:
    """The crash, and the first near miss of each close call, with the frame and what the expert wanted."""
    found, last_near = [], -99
    for i, s in enumerate(steps):
        kind = "crash" if s["collided"] else "near miss" if s["clearance"] < NEAR else None
        if not kind or (kind == "near miss" and i - last_near < 6):
            continue
        last_near = i
        found.append({"scenario": sc["id"], "step": i + 1, "kind": kind, "clearance": round(s["clearance"], 2),
                      "pilot": s["action"], "expert": s["expert"], "thumb": frames[i]})
    return found


def _returns(steps) -> np.ndarray:
    g, out = 0.0, np.zeros(len(steps), np.float32)
    for i in range(len(steps) - 1, -1, -1):
        g = steps[i]["reward"] + GAMMA * g
        out[i] = g
    return out


def _weights(steps) -> np.ndarray:
    w = np.ones(len(steps), np.float32)
    for i, s in enumerate(steps):
        if s["collided"] or s["clearance"] < NEAR:
            w[max(0, i - MISTAKE_WINDOW):i + 1] = MISTAKE_WEIGHT
    return w


class Trainer:
    def __init__(self, base: Path | None, run_id: str, progress=None, workers: int = 10):
        self.pilot = Pilot.load(base) if base else Pilot()
        self.pilot_meta = {k: v for k, v in self.pilot.meta.items() if k in ("name", "trained_on", "demonstrations", "flights")}
        self.base = base
        self.run_id = run_id
        self.dir = LAB / run_id
        (self.dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        self.progress = progress or (lambda **k: None)
        self.workers = workers
        self.dataset = []  # aggregated (DAgger) expert-labelled states, with mistake weights
        self.rows = []
        self.opt = torch.optim.Adam(self.pilot.net.parameters(), lr=1e-3)

    # ------------------------------------------------------------------ parallel rollouts
    def _fly(self, pool, state, scs, temperature, seed, **extra) -> list[dict]:
        n = max(1, min(self.workers, len(scs)))
        jobs = [{"state": state, "scenarios": scs[i::n], "temperature": temperature, "seed": seed + i, **extra} for i in range(n)]
        eps = [e for batch in pool.map(rollout_worker, jobs) for e in batch]
        order = {sc["id"]: i for i, sc in enumerate(scs)}
        return sorted(eps, key=lambda e: order[e["scenario"]["id"]])

    def evaluate(self, pool, state, bench, version: str, thumbs=False) -> dict:
        eps = self._fly(pool, state, bench, 0.0, 0, thumbs=thumbs, keep_steps=False)
        n = len(eps)
        row = {"version": version, "crash_rate": round(sum(e["crashed"] for e in eps) / n, 3),
               "mean_distance_m": round(float(np.mean([e["distance"] for e in eps])), 2),
               "near_miss_steps": round(float(np.mean([e["near"] for e in eps])), 2),
               "min_clearance_m": round(float(np.mean([e["min_clearance"] for e in eps])), 2),
               "expert_agreement": round(float(np.mean([e["agreement"] for e in eps])), 3),
               "success_rate": round(sum((not e["crashed"]) for e in eps) / n, 3)}
        return {"row": row, "episodes": eps}

    # ------------------------------------------------------------------ one learning step
    def update(self, episodes, epochs=3, bs=256, beta=1.0) -> dict:
        net = self.pilot.net
        fresh, n_mistakes = [], 0
        for ep in episodes:
            g, w = _returns(ep["steps"]), _weights(ep["steps"])
            n_mistakes += int(ep["crashed"]) + int(sum(1 for s in ep["steps"] if s["clearance"] < NEAR) > 0)
            for s, gi, wi in zip(ep["steps"], g, w):
                fresh.append({**s, "ret": float(gi), "w": float(wi)})
        self.dataset.extend({k: s[k] for k in ("prev", "cur", "active", "expert", "w")} for s in fresh)
        self.dataset = self.dataset[-30000:]

        # Advantages for this iteration's own decisions, from the value head before the update.
        x_f, a_f = batch(fresh)
        net.eval()
        with torch.no_grad():
            _, v = net(x_f, a_f)
        ret = torch.tensor([s["ret"] for s in fresh])
        adv = ret - v
        adv = (adv - adv.mean()) / (adv.std() + 1e-6)
        awr_w = torch.clamp(torch.exp(adv / beta), max=10.0)
        taken = torch.tensor([INDEX[s["action"]] for s in fresh])

        # Behaviour cloning on the aggregated, expert-relabelled dataset.
        idx = np.random.default_rng(len(self.rows)).choice(len(self.dataset), size=min(len(self.dataset), 12000), replace=False)
        bc = [self.dataset[i] for i in idx]
        x_b, a_b = batch(bc)
        y_b = torch.tensor([INDEX[s["expert"]] for s in bc])
        w_b = torch.tensor([s["w"] for s in bc])

        ce = nn.CrossEntropyLoss(reduction="none")
        net.train()
        losses = []
        for _ in range(epochs):
            pb, pf = torch.randperm(len(y_b)), torch.randperm(len(taken))
            for i in range(0, len(pb), bs):
                bi = pb[i:i + bs]
                logits, _ = net(x_b[bi], a_b[bi])
                loss_bc = (ce(logits, y_b[bi]) * w_b[bi]).sum() / w_b[bi].sum()
                fi = pf[torch.arange(i, i + bs) % len(pf)]  # cycle through this iteration's own decisions
                lf, vf = net(x_f[fi], a_f[fi])
                loss_rl = -(awr_w[fi] * torch.log_softmax(lf, 1)[torch.arange(len(fi)), taken[fi]]).mean()
                loss_v = nn.functional.mse_loss(vf, ret[fi])
                loss = loss_bc + 0.5 * loss_rl + 0.25 * loss_v
                self.opt.zero_grad()
                loss.backward()
                self.opt.step()
                losses.append((loss_bc.item(), loss_rl.item(), loss_v.item()))
        net.eval()
        l = np.mean(losses, axis=0)
        return {"states": len(fresh), "dataset": len(self.dataset), "mistakes": n_mistakes,
                "loss_imitation": round(float(l[0]), 3), "loss_rl": round(float(l[1]), 3), "loss_value": round(float(l[2]), 3)}

    # ------------------------------------------------------------------ the whole loop
    def run(self, iterations=8, episodes=48, bench_n=32, beta0=0.5, beta_decay=0.6, stop=lambda: False) -> dict:
        bench = scenarios(bench_n, seed=2026)  # held out: never trained on
        ctx = mp.get_context("spawn")
        t0 = time.time()
        with ctx.Pool(self.workers) as pool:
            self.progress(stage="Scoring the imported pilot (v0) on the benchmark", iteration=0)
            ev0 = self.evaluate(pool, self.pilot.state(), bench, "v0", thumbs=True)
            ev0["row"].update(iteration=0, seconds=round(time.time() - t0, 1))
            self.rows.append(ev0["row"])
            self.pilot.save(self.dir / "checkpoints" / "v0.pt", {"source": str(self.base)})
            best = (self._score(ev0["row"]), "v0", self.pilot.state())
            self.progress(rows=self.rows)
            for it in range(1, iterations + 1):
                if stop():
                    break
                # DAgger schedule: early on the expert takes over some decisions so a weak pilot still
                # reaches the hard parts of each flight; the pilot flies alone after a few iterations.
                beta = round(beta0 * beta_decay ** (it - 1), 3) if beta0 * beta_decay ** (it - 1) >= 0.05 else 0.0
                # Smaller steps as it improves: once the expert has handed over, full-size updates on the
                # pilot's own (rarer) mistakes made later versions swing (measured: 6% -> 22-31% crashes).
                for g in self.opt.param_groups:
                    g["lr"] = 1e-3 * 0.8 ** (it - 1)
                self.progress(stage=f"Iteration {it}: flying {episodes} training scenarios and collecting mistakes", iteration=it)
                eps = self._fly(pool, self.pilot.state(), scenarios(episodes, seed=1000 + it), 0.5, it * 100, beta=beta)
                self.progress(stage=f"Iteration {it}: learning from {sum(e['crashed'] for e in eps)} crashes and every near miss")
                stats = self.update(eps)
                self.progress(stage=f"Iteration {it}: re-scoring v{it} on the held-out benchmark")
                ev = self.evaluate(pool, self.pilot.state(), bench, f"v{it}")
                row = {**ev["row"], **stats, "iteration": it, "beta": beta,
                       "train_crash_rate": round(sum(e["crashed"] for e in eps) / len(eps), 3),
                       "seconds": round(time.time() - t0, 1)}
                self.rows.append(row)
                self.pilot.save(self.dir / "checkpoints" / f"v{it}.pt", {"row": row})
                if self._score(row) > best[0]:
                    best = (self._score(row), f"v{it}", self.pilot.state())
                self.progress(rows=self.rows)
                self._write(ev0, None, None)
            # Before / after on identical scenarios, and which of v0's mistakes are fixed.
            self.progress(stage=f"Comparing v0 with the best version ({best[1]}) on the same scenarios")
            ev_best = self.evaluate(pool, best[2], bench, best[1], thumbs=True)
            fixed = self._fixed(ev0["episodes"], ev_best["episodes"])
            replay_ids = self._replay_ids(ev0["episodes"], ev_best["episodes"])
            v0_state = Pilot.load(self.dir / "checkpoints" / "v0.pt").state()
            traces = {}
            for version, state in (("v0", v0_state), (best[1], best[2])):
                eps = self._fly(pool, state, [sc for sc in bench if sc["id"] in replay_ids], 0.0, 0,
                                size=(384, 216), record_dir=str(self.dir / "replays" / version), keep_steps=False)
                traces[version] = {e["scenario"]["id"]: {"trace": e["trace"], "crashed": e["crashed"], "length": e["length"],
                                                         "distance": round(e["distance"], 1)} for e in eps}
        torch.save({"state": best[2], "arch": ARCH, "actions": ACTIONS, "meta": {"from": self.run_id, "version": best[1], "row": next((r for r in self.rows if r["version"] == best[1]), None), "base": self.pilot_meta}},
                   DATA / "models" / f"lab-{self.run_id}-{best[1]}.pt")
        return self._write(ev0, ev_best, {"best": best[1], "fixed": fixed, "replays": replay_ids, "replay_traces": traces,
                                          "model_file": f"lab-{self.run_id}-{best[1]}.pt"})

    @staticmethod
    def _score(row) -> float:
        return row["mean_distance_m"] - 30 * row["crash_rate"] - 0.5 * row["near_miss_steps"]

    @staticmethod
    def _fixed(before, after) -> list[dict]:
        out = []
        by_id = {e["scenario"]["id"]: e for e in after}
        for e in before:
            for m in e.get("mistakes", []):
                a = by_id[m["scenario"]]
                if m["kind"] == "crash":
                    ok = not a["crashed"]
                else:
                    window = a["trace"][max(0, m["step"] - 4):m["step"] + 3]
                    ok = all(t["c"] >= NEAR for t in window) and not a["crashed"]
                after_m = next((x for x in a.get("mistakes", []) if abs(x["step"] - m["step"]) <= 4), None)
                out.append({**m, "fixed": ok, "after_thumb": after_m["thumb"] if after_m else None,
                            "after_crashed": a["crashed"], "after_distance": round(a["distance"], 1)})
        return out

    @staticmethod
    def _replay_ids(before, after) -> list[str]:
        by_id = {e["scenario"]["id"]: e for e in after}
        turned = [e["scenario"]["id"] for e in before if e["crashed"] and not by_id[e["scenario"]["id"]]["crashed"]]
        rest = [e["scenario"]["id"] for e in before if e["crashed"]]
        return (turned + [r for r in rest if r not in turned])[:3]

    def _write(self, ev0, ev_best, final) -> dict:
        def summary(ev):
            return [{k: e[k] for k in ("crashed", "distance", "near", "min_clearance", "agreement", "length")} | {"scenario": e["scenario"]}
                    for e in ev["episodes"]] if ev else None
        out = {"id": self.run_id, "base": self.base.name if self.base else "fresh", "base_meta": self.pilot_meta,
               "rows": self.rows, "final": final,
               "episodes_before": summary(ev0), "episodes_after": summary(ev_best),
               "max_steps": MAX_STEPS, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
        (self.dir / "run.json").write_text(json.dumps(out), encoding="utf-8")
        return out
