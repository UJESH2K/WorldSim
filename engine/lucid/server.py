"""HTTP control plane for the dashboard.

    uvicorn lucid.server:app --port 8765        (from engine/)

One job at a time:
  flight    live third-person flight; WASD from the browser or the autopilot; Sentinel on
  autotune  score autopilot settings over short flights, keep the best
  train     DAgger: distil the reflex into a pixels-only student (mock world)
Every LingBot job needs an explicit `seconds` cap and stops itself before it.
"""
import asyncio
import base64
import json
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from . import budget, places, twin
from .actions import EMBODIMENTS
from .config import DATA
from .dagger import train
from .lab.api import router as lab_router
from .flight import FlightState, autotune, fly
from .loop import Telemetry
from .prompts import WORLDS
from .sentinel import Narrator, load_detector
from .worlds.mock import MockWorld
from .worlds.photo import PhotoWorld
from .worlds.reactor_world import ReactorWorld

app = FastAPI(title="Lucid engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(lab_router)  # Pilot Lab + world-model audits

tel = Telemetry()
flight = FlightState()
narrator = Narrator("qwen2.5vl:3b")  # one warm local VLM for every flight
narrator.warm_up()
threading.Thread(target=load_detector, daemon=True).start()  # so the first Fly is instant
_task: asyncio.Task | None = None
_job = {"kind": None}


class JobRequest(BaseModel):
    world: str = "mock"  # mock | reactor
    scene: str = "forest"
    seconds: int = 120  # reactor only: hard GPU-second cap for this job
    confirm_spend: bool = False  # reactor only: the person said yes to the cost; nothing is charged without it
    autopilot: bool = True
    flights_per: int = 2  # autotune
    max_chunks: int = 30  # autotune flight length
    rounds: int = 3  # train
    episodes_per_round: int = 6
    eval_episodes: int = 6


def _latest_model() -> Path | None:
    models = sorted((DATA / "models").glob("*.pt"))
    return models[-1] if models else None


async def _open_world(req: JobRequest):
    if req.world == "reactor":
        world = ReactorWorld("drone", log=tel.say)
        world.on_display = tel.frame  # every received frame, at display rate
        await world.open(planned_seconds=req.seconds)
        return world
    if places.is_custom(req.scene):
        # Your own place: practise inside the actual photo, free.
        world = PhotoWorld("drone", realtime=_job["kind"] == "flight")
        if _job["kind"] == "flight":
            world.on_display = tel.frame
        return world
    return MockWorld("drone", realtime=_job["kind"] == "flight", size=(384, 216))


async def _run(kind: str, req: JobRequest):
    world = None
    try:
        tel.status, tel.stop_requested = "starting", False
        world = await _open_world(req)
        tel.status = "running"
        if kind == "flight":
            tel.detail = f"flying: {WORLDS[req.scene].title}"
            score = await fly(world, req.scene, flight, tel, seed=int(time.time()) % 10_000, narrator=narrator)
            tel.say(f"flight over: {score['chunks']} decisions, {score['warning']} warnings, "
                    f"{score['collision']} collisions")
        elif kind == "autotune":
            await autotune(world, req.scene, flight, tel, flights_per=req.flights_per, max_chunks=req.max_chunks)
        else:
            await train(world, tel, rounds=req.rounds, episodes_per_round=req.episodes_per_round,
                        eval_episodes=req.eval_episodes)
        tel.status = "stopped" if tel.stop_requested else "done"
    except budget.BudgetExceeded as e:
        tel.status = "stopped: budget"
        tel.say(str(e))
    except Exception as e:  # noqa: BLE001 - surface every failure on the dashboard
        tel.status = "error"
        tel.say(f"error: {e!r}")
    finally:
        if world is not None:
            await world.close()
            tel.usage = world.usage()
        tel.detail = ""
        _job["kind"] = None


async def _start(kind: str, req: JobRequest):
    global _task
    if _task and not _task.done():
        raise HTTPException(409, "something is already running; POST /stop first")
    if req.scene not in WORLDS:
        raise HTTPException(400, f"scene must be one of {list(WORLDS)}")
    if kind == "train" and req.world != "mock":
        raise HTTPException(400, "training runs on the mock world; fly or auto-tune on LingBot")
    if req.world == "reactor" and not req.confirm_spend:
        raise HTTPException(428, "This uses paid Reactor credit and needs your confirmation first.")
    if req.world == "reactor":
        try:
            budget.authorize("reactor/lingbot-world-2", req.seconds)
        except budget.BudgetExceeded as e:
            raise HTTPException(402, str(e)) from e
    _job["kind"] = kind
    tel.config = {"kind": kind, **req.model_dump()}
    tel.steps.clear()
    tel.episodes.clear()
    if kind == "flight":
        tune, params = flight.tune, flight.params
        flight.reset()
        flight.tune, flight.params = tune, params  # keep the last auto-tune result on screen
        flight.world, flight.scene, flight.autopilot = req.world, req.scene, req.autopilot
    _task = asyncio.create_task(_run(kind, req))
    return {"ok": True, "config": tel.config}


@app.post("/flight")
async def start_flight(req: JobRequest):
    return await _start("flight", req)


@app.post("/autotune")
async def start_autotune(req: JobRequest):
    flight.world, flight.scene = req.world, req.scene
    return await _start("autotune", req)


@app.post("/train")
async def start_train(req: JobRequest):
    return await _start("train", req)


@app.post("/stop")
async def stop():
    tel.stop_requested = True
    return {"ok": True}


class Control(BaseModel):
    action: str | None = None  # None = keys released


@app.post("/control")
async def control(body: Control):
    if body.action is not None and body.action not in EMBODIMENTS["drone"]:
        raise HTTPException(400, f"unknown action {body.action}")
    flight.manual = body.action
    return {"ok": True}


class Toggle(BaseModel):
    on: bool


@app.post("/autopilot")
async def set_autopilot(body: Toggle):
    flight.autopilot = body.on
    return {"ok": True, "autopilot": flight.autopilot}


class Brain(BaseModel):
    brain: str  # reflex | learned
    model: str | None = None  # a Pilot Lab checkpoint in data/models; default: the newest Lab result


@app.post("/autopilot/brain")
async def set_brain(body: Brain):
    if body.brain == "reflex":
        flight.brain = "reflex"
        return {"ok": True, "brain": "reflex"}
    if body.brain != "learned":
        raise HTTPException(400, "brain is reflex or learned")
    from .lab.pilot import Pilot

    models = DATA / "models"
    if body.model:
        path = models / body.model
        if "/" in body.model or "\\" in body.model or not path.exists():
            raise HTTPException(404, "no such pilot")
    else:
        import torch

        def held_out_crash(f: Path) -> float:  # the best-scoring Lab result flies by default
            try:
                row = torch.load(f, weights_only=True, map_location="cpu").get("meta", {}).get("row") or {}
            except Exception:  # noqa: BLE001 - unreadable file: last choice
                return 2.0
            return row.get("crash_rate", 1.0)

        found = sorted(models.glob("lab-*.pt"), key=held_out_crash)
        if not found:
            raise HTTPException(404, "no Lab pilot yet: run the Pilot Lab first")
        path = found[0]
    try:
        net = await asyncio.to_thread(Pilot.load, path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    meta = net.meta or {}
    name = meta.get("version", path.stem)
    flight.learned, flight.brain = (name, net), "learned"
    tel.say(f"autopilot brain: learned pilot {name} ({path.name})")
    return {"ok": True, "brain": "learned", "name": name, "file": path.name, "row": meta.get("row")}


class Event(BaseModel):
    label: str


@app.post("/event")
async def event(body: Event):
    flight.events.append(body.label)
    return {"ok": True}


@app.get("/state")
async def state():
    return {"status": tel.status, "detail": tel.detail, "job": _job["kind"], "config": tel.config,
            "log": list(tel.log)[-40:], "usage": tel.usage, "rounds": tel.rounds,
            "budget": {k: v for k, v in budget.summary().items() if k != "sessions"},
            "model": _latest_model().name if _latest_model() else None, "flight": flight.snapshot()}


@app.get("/catalog")
async def catalog():
    return {"worlds": [{"key": w.key, "title": w.title, "events": list(w.events), "drone_box": w.drone_box,
                        "custom": places.is_custom(w.key),
                        "thumb": f"/engine/places/{w.key}/thumb.jpg" if places.is_custom(w.key) else f"/scenes/{w.key}.jpg"}
                       for w in WORLDS.values()],
            "rate_per_second": budget.rate_per_second("reactor/lingbot-world-2")}


class PlaceUpload(BaseModel):
    image_b64: str  # JPEG/PNG bytes, base64 (the browser downsizes to <= 1920 px first)
    title: str = ""
    description: str = ""  # empty: the local VLM describes the photo


@app.post("/places")
async def add_place(body: PlaceUpload):
    try:
        raw = base64.b64decode(body.image_b64.split(",")[-1])
        entry = await asyncio.to_thread(places.add, raw, body.title, body.description)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    tel.say(f"new place '{entry['title']}': {entry['description']} (described by {entry['described_by']})")
    return entry


@app.delete("/places/{key}")
async def delete_place(key: str):
    if _task and not _task.done() and tel.config.get("scene") == key:
        raise HTTPException(409, "that place is in use by the current flight")
    try:
        places.remove(key)
    except KeyError as e:
        raise HTTPException(404, "no such place") from e
    return {"ok": True}


@app.get("/places/{key}/thumb.jpg")
async def place_thumb(key: str):
    path = places.CUSTOM_DIR / f"{key}_thumb.jpg"
    if not places.is_custom(key) or not path.exists():
        raise HTTPException(404, "no such place")
    return Response(path.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@app.get("/reports")
async def list_reports():
    """Newest first: one line per flight report."""
    out = []
    for f in sorted(twin.REPORTS.glob("*.json"), reverse=True)[:50]:
        r = json.loads(f.read_text(encoding="utf-8"))
        out.append({"id": r["id"], "at": r["at"], "world": r["world"], "scene": r["scene"]["title"], "verdict": r["verdict"],
                    "distance_m": r["metrics"]["distance_m"], "collisions": r["metrics"]["collisions"]})
    return out


@app.get("/reports/{rid}")
async def get_report(rid: str):
    f = twin.REPORTS / f"{rid}.json"
    if "/" in rid or "\\" in rid or not f.exists():
        raise HTTPException(404, "no such report")
    return json.loads(f.read_text(encoding="utf-8"))


@app.get("/calibration")
async def calibration():
    return json.loads(twin.CALIB_FILE.read_text(encoding="utf-8")) if twin.CALIB_FILE.exists() else {}


@app.get("/physics/model")
async def physics_model():
    from .control import CommandProfile, Gains
    from .physics import QuadParams

    return {"airframe": "Phantom 2 class quadrotor", "params": QuadParams().to_dict(), "gains": Gains().to_dict(),
            "commands": CommandProfile().__dict__, "rate_hz": twin.PHYSICS_HZ}


@app.get("/budget")
async def budget_state():
    return budget.summary()


@app.get("/probes")
async def probes():
    out = []
    for p in sorted((DATA / "probes").glob("*.json"), reverse=True):
        r = json.loads(p.read_text(encoding="utf-8"))
        out.append({k: r.get(k) for k in ("run", "chunks_per_s", "obedience", "presence_mean", "usage")})
    return out


@app.get("/frame.jpg")
async def frame():
    if tel.jpeg is None:
        raise HTTPException(404, "no frame yet")
    return Response(tel.jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/stream.mjpg")
async def stream():
    async def gen():
        last = None
        while True:
            if tel.jpeg is not None and tel.jpeg is not last:
                last = tel.jpeg
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + last + b"\r\n"
            await asyncio.sleep(0.02)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/health")
async def health():
    return {"ok": True, "time": time.time()}
