"""Your own place: turn an uploaded photo (the venue, a room, a warehouse) into a flyable world.

    photo -> cropped to 16:9 at LingBot's 1664x960 -> the drone composited at the centre
          -> a scene description (yours, or the local VLM's) -> a layered-prompt world

Places persist in engine/data/custom_worlds.json and are registered into WORLDS at import,
so they survive engine restarts and every flight mode (practice, real AI, auto-tune) can use them.
"""
import base64
import json
import re
import time
import urllib.request

import cv2
import numpy as np

from .config import ASSETS, DATA
from .prompts import WORLDS, World

W, H = 1664, 960
CUSTOM_DIR = ASSETS / "seeds" / "custom"
REGISTRY = DATA / "custom_worlds.json"
DRONE = ASSETS / "seeds" / "drone_cutout.png"

INDOOR_EVENTS = {
    "person steps in": "a person walks into the space directly ahead of the drone.",
    "chair pushed in": "a chair is pushed into the path directly ahead of the drone.",
    "door swings open": "a door swings open into the path ahead of the drone.",
    "lights dim": "the lights dim and the room drops into low, uneven light.",
}
_KEEP = "The drone remains the main subject, unchanged in size and position, while "


def fit16x9(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    if w / h > W / H:
        nw = int(h * W / H)
        img = img[:, (w - nw) // 2:(w - nw) // 2 + nw]
    else:
        nh = int(w * H / W)
        img = img[(h - nh) // 2:(h - nh) // 2 + nh]
    return cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA if img.shape[1] > W else cv2.INTER_CUBIC)


def compose_seed(scene: np.ndarray, cx=0.5, cy=0.54, width=0.24, shadow_dy=0.22):
    """Same compositing as the built-in seeds: drone at the centre, brightness-matched, soft shadow."""
    out = scene.astype(np.float32)
    drone = cv2.imread(str(DRONE), cv2.IMREAD_UNCHANGED)
    dw = int(W * width)
    dh = int(drone.shape[0] * dw / drone.shape[1])
    d = cv2.resize(drone, (dw, dh), interpolation=cv2.INTER_AREA)
    rgb, a = d[..., :3].astype(np.float32), d[..., 3:].astype(np.float32) / 255.0
    x0, y0 = int(W * cx - dw / 2), int(H * cy - dh / 2)
    sh = np.zeros((H, W), np.float32)
    cv2.ellipse(sh, (int(W * cx), int(H * (cy + shadow_dy))), (int(dw * 0.42), int(dh * 0.16)), 0, 0, 360, 1.0, -1)
    out *= 1 - cv2.GaussianBlur(sh, (0, 0), 18)[..., None] * 0.35
    region = out[y0:y0 + dh, x0:x0 + dw]
    gain = np.clip(region.mean() / max(1.0, (rgb * a).sum() / max(1.0, a.sum())) * 1.35, 0.55, 1.0)
    out[y0:y0 + dh, x0:x0 + dw] = region * (1 - a) + rgb * gain * a
    box = (round(x0 / W, 3), round(y0 / H, 3), round(dw / W, 3), round(dh / H, 3))
    return np.clip(out, 0, 255).astype(np.uint8), box


def describe(img: np.ndarray, model: str = "qwen2.5vl:3b") -> str | None:
    """A short phrase for the base prompt, from the local VLM. None if Ollama is not running."""
    jpg = cv2.imencode(".jpg", cv2.resize(img, (640, 369)))[1].tobytes()
    body = {"model": model, "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0, "num_predict": 60, "num_ctx": 4096},
            "messages": [{"role": "user", "images": [base64.b64encode(jpg).decode()], "content":
                          "Describe this place as one short noun phrase for a scene description, for example "
                          "'a hotel conference hall with rows of chairs and a stage'. Reply with the phrase only."}]}
    try:
        req = urllib.request.Request("http://localhost:11434/api/chat", json.dumps(body).encode(),
                                     {"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            text = (json.load(r)["message"].get("content") or "").strip()
    except Exception:
        return None
    text = text.strip(" .\"'\n")
    letters = sum(c.isalpha() or c == " " for c in text)
    if not text or letters / len(text) < 0.8:
        return None
    return text[:240]


def _world(entry: dict) -> World:
    desc = entry["description"].rstrip(". ")
    if not re.match(r"^(a|an|the)\b", desc, re.I):
        desc = "a " + desc
    x, y, w, h = entry["drone_box"]
    return World(
        key=entry["key"],
        title=entry["title"],
        image=f"custom/{entry['key']}_drone.jpg",
        base=("A small white quadcopter drone with red stripes, four spinning rotors and a black camera gimbal "
              f"flies at waist height inside {desc}. The world contains EXACTLY ONE drone. "
              "Walls, furniture and fixtures stay fixed in place, natural indoor light, photorealistic."),
        events={k: _KEEP + v for k, v in INDOOR_EVENTS.items()},
        mock={"palette": "warehouse", "density": 5.0},
        drone_box=(x, y, w, h),
        flow_mask=(round(x - 0.03, 3), round(y - 0.04, 3), round(w + 0.06, 3), round(h + 0.08, 3)),
    )


def _read() -> list[dict]:
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else []


def _write(entries: list[dict]) -> None:
    REGISTRY.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def load() -> None:
    for e in _read():
        if (CUSTOM_DIR / f"{e['key']}_drone.jpg").exists():
            WORLDS[e["key"]] = _world(e)


def add(image_bytes: bytes, title: str = "", description: str = "") -> dict:
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("That file is not an image we can read (use JPG or PNG).")
    if min(img.shape[:2]) < 360:
        raise ValueError("The photo is too small; use one at least 640 pixels wide.")
    scene = fit16x9(img)
    seed, box = compose_seed(scene)
    key = "place-" + time.strftime("%Y%m%d-%H%M%S")
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(CUSTOM_DIR / f"{key}.jpg"), scene, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(CUSTOM_DIR / f"{key}_drone.jpg"), seed, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(CUSTOM_DIR / f"{key}_thumb.jpg"), cv2.resize(seed, (640, 369), interpolation=cv2.INTER_AREA),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    described_by = "you"
    if not description.strip():
        description = describe(scene) or "an indoor room"
        described_by = "local AI" if description != "an indoor room" else "default"
    entry = {"key": key, "title": (title.strip() or "Your place")[:40], "description": description.strip()[:240],
             "described_by": described_by, "drone_box": list(box), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _write([e for e in _read() if e["key"] != key] + [entry])
    WORLDS[key] = _world(entry)
    return entry


def remove(key: str) -> None:
    entries = _read()
    if not any(e["key"] == key for e in entries):
        raise KeyError(key)
    _write([e for e in entries if e["key"] != key])
    WORLDS.pop(key, None)
    for suffix in ("", "_drone", "_thumb"):
        (CUSTOM_DIR / f"{key}{suffix}.jpg").unlink(missing_ok=True)


def is_custom(key: str) -> bool:
    return key.startswith("place-")


load()
