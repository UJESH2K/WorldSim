"""Pilot Lab and world-model audits over HTTP.

  GET  /lab/pilots                 pilots the Lab can fly (factory, uploads, every Lab result)
  POST /lab/pilots                 import a pilot's weights (.pt, base64)
  POST /lab/runs                   start an improvement run (a separate process; free, local CPU)
  POST /lab/stop                   finish the current run early (it still writes the before/after)
  GET  /lab/runs                   one line per run
  GET  /lab/runs/{id}              curves, mistakes, replays, live progress
  GET  /lab/runs/{id}/frame/{version}/{scenario}/{k}.jpg   replay frames
  GET  /audits, /audits/{run}      world-model audits of recorded LingBot flights
"""
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..config import DATA
from .pilot import ARCH, Pilot
from .train import LAB

router = APIRouter()
MODELS = DATA / "models"
ENGINE = Path(__file__).resolve().parents[2]
_proc: dict = {"p": None, "run": None}
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _running() -> str | None:
    p = _proc["p"]
    return _proc["run"] if p is not None and p.poll() is None else None


def _pilot_info(path: Path) -> dict | None:
    import torch

    try:
        blob = torch.load(path, weights_only=True, map_location="cpu")
    except Exception:  # noqa: BLE001 - not a checkpoint
        return None
    if not isinstance(blob, dict) or blob.get("arch") != ARCH:
        return None
    meta = blob.get("meta") or {}
    if path.name.startswith("lab-"):
        name = f"Lab result {meta.get('version', '')} ({meta.get('from', '')})".strip()
    else:
        name = meta.get("name") or path.stem
    return {"file": path.name, "name": name, "trained_on": meta.get("trained_on"), "scores": meta.get("scores"),
            "source": "lab" if path.name.startswith("lab-") else "upload" if path.name.startswith("upload-") else "factory",
            "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))}


@router.get("/lab/pilots")
async def pilots():
    out = [i for i in (_pilot_info(p) for p in sorted(MODELS.glob("*.pt"), key=lambda p: -p.stat().st_mtime)) if i]
    return sorted(out, key=lambda i: {"factory": 0, "upload": 1, "lab": 2}[i["source"]])


class PilotUpload(BaseModel):
    name: str
    data_b64: str


@router.post("/lab/pilots")
async def import_pilot(body: PilotUpload):
    raw = base64.b64decode(body.data_b64.split(",")[-1])
    if len(raw) > 50_000_000:
        raise HTTPException(413, "pilot file is too large (50 MB max)")
    slug = re.sub(r"[^a-z0-9]+", "-", body.name.lower().rsplit(".", 1)[0]).strip("-")[:40] or "pilot"
    tmp = MODELS / f".incoming-{slug}.pt"
    tmp.write_bytes(raw)
    try:
        pilot = Pilot.load(tmp)
    except Exception as e:  # noqa: BLE001 - tell the person why
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f"Not a pilot the Lab can fly: {e}") from None
    dest = MODELS / f"upload-{slug}.pt"
    pilot.save(dest, {**pilot.meta, "name": pilot.meta.get("name") or body.name, "uploaded": time.strftime("%Y-%m-%d %H:%M")})
    tmp.unlink(missing_ok=True)
    return _pilot_info(dest)


class RunRequest(BaseModel):
    base: str = "factory-pilot.pt"
    iterations: int = 10
    episodes: int = 48


@router.post("/lab/runs")
async def start_run(req: RunRequest):
    if _running():
        raise HTTPException(409, f"run {_running()} is still going; stop it first")
    base = MODELS / req.base
    if not _SAFE.match(req.base) or not base.exists():
        raise HTTPException(400, "no such pilot")
    if not (1 <= req.iterations <= 30 and 8 <= req.episodes <= 128):
        raise HTTPException(400, "iterations 1-30, episodes 8-128")
    run = time.strftime("lab-%Y%m%d-%H%M%S")
    (LAB / run).mkdir(parents=True, exist_ok=True)
    log = open(LAB / run / "process.log", "w", encoding="utf-8")  # noqa: SIM115 - owned by the child
    _proc["p"] = subprocess.Popen(
        [sys.executable, "-m", "lucid.lab.run", "--run", run, "--base", str(base),
         "--iterations", str(req.iterations), "--episodes", str(req.episodes)],
        cwd=str(ENGINE), stdout=log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))  # a live flight stays smooth
    _proc["run"] = run
    return {"run": run}


@router.post("/lab/stop")
async def stop_run():
    run = _running()
    if not run:
        return {"ok": True, "running": None}
    (LAB / run / "STOP").write_text("stop", encoding="utf-8")
    return {"ok": True, "running": run}


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@router.get("/lab/runs")
async def runs():
    out = []
    for d in sorted(LAB.glob("lab-*"), reverse=True):
        r, prog = _read(d / "run.json") or {}, _read(d / "progress.json") or {}
        rows = r.get("rows") or prog.get("rows") or []
        if not rows and not prog:
            continue
        best = (r.get("final") or {}).get("best")
        best_row = next((x for x in rows if x["version"] == best), rows[-1] if rows else None)
        out.append({"id": d.name, "base": r.get("base") or prog.get("base"), "base_name": (r.get("base_meta") or {}).get("name"),
                    "status": "running" if _running() == d.name else prog.get("status", "done" if best else "incomplete"),
                    "versions": len(rows), "best": best,
                    "before": rows[0] if rows else None, "after": best_row, "updated": r.get("updated") or prog.get("updated")})
    return out


@router.get("/lab/runs/{rid}")
async def run_detail(rid: str):
    d = LAB / rid
    if not _SAFE.match(rid) or not d.is_dir():
        raise HTTPException(404, "no such run")
    r, prog = _read(d / "run.json") or {}, _read(d / "progress.json") or {}
    status = "running" if _running() == rid else prog.get("status", "done" if (r.get("final") or {}).get("best") else "incomplete")
    frames = {}
    for vdir in (d / "replays").glob("*"):
        frames[vdir.name] = {s.name: len(list(s.glob("*.jpg"))) for s in vdir.iterdir() if s.is_dir()}
    return {**r, "rows": r.get("rows") or prog.get("rows") or [], "progress": prog, "status": status, "frames": frames}


@router.get("/lab/runs/{rid}/frame/{version}/{scenario}/{k}.jpg")
async def replay_frame(rid: str, version: str, scenario: str, k: int):
    if not all(_SAFE.match(x) for x in (rid, version, scenario)):
        raise HTTPException(404, "no such frame")
    f = LAB / rid / "replays" / version / scenario / f"{k:03d}.jpg"
    if not f.exists():
        raise HTTPException(404, "no such frame")
    return Response(f.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


# ---------------------------------------------------------------- world-model audits
@router.get("/audits")
async def audits():
    out = []
    for f in sorted((DATA / "bank").glob("flight-*/ep*/audit.json"), reverse=True):
        a = _read(f)
        if not a:
            continue
        out.append({"run": f.parent.parent.name, "episode": f.parent.name, "scene": a.get("scene"), "world": a.get("world"),
                    "chunks": a.get("chunks"), "trusted_share": a.get("trusted_share"), "counts": a.get("counts"),
                    "first_failure": a.get("first_failure"), "reanchors": a.get("reanchors", 0)})
    return out


@router.get("/audits/{run}")
async def audit_detail(run: str):
    if not _SAFE.match(run):
        raise HTTPException(404, "no such audit")
    f = next((DATA / "bank" / run).glob("ep*/audit.json"), None)
    if f is None:
        raise HTTPException(404, "no such audit")
    return _read(f)


@router.get("/audits/{run}/frame/{k}.jpg")
async def audit_frame(run: str, k: int):
    if not _SAFE.match(run):
        raise HTTPException(404, "no such frame")
    ep = next((p for p in (DATA / "bank" / run).glob("ep*") if p.is_dir()), None)
    f = ep / "frames" / f"{k:04d}.jpg" if ep else None
    if f is None or not f.exists():
        raise HTTPException(404, "no such frame")
    return Response(f.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})
