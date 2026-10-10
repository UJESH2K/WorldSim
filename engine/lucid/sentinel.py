"""The Sentinel: calls crashes, near misses and broken worlds, every control step.

A world model has no collision physics, so "did the drone crash?" has to be read off the
pixels. Small vision-language models cannot do it reliably (measured: qwen2.5-vl and
qwen3-vl both called a person touching the drone "clear"), so the verdict is built from
signals that can each be checked:

  detector  YOLO11n boxes -> geometry against the drone's own box: overlap = collision,
            within half a drone-width or in the corridor ahead = warning.
  looming   optical-flow divergence around the drone (lucid.perception): unlabelled
            obstacles such as posts and trunks that the detector has no class for.
  presence  the drone's own pixels still match the seed's drone; when they stop, the
            world model dropped or morphed its subject and nothing it shows can be trusted.
  obedience the world kept ignoring the controls for several steps.

A local VLM (qwen3-vl via Ollama) runs beside it as a narrator: one plain sentence about
what is around the drone, shown to people, never used as the verdict.
"""
import base64
import json
import os
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from .config import ASSETS, DATA
from .prompts import World as WorldSpec

os.environ.setdefault("YOLO_AUTOINSTALL", "false")  # never let ultralytics pip-install into our env
os.environ.setdefault("YOLO_OFFLINE", "true")

SEVERITY = {"clear": 0, "caution": 1, "warning": 2, "collision": 3, "anomaly": 3}
# COCO classes that can be a hazard for a low-flying drone. The drone itself is often
# misread as bench / table / kite, which the self-filter below removes.
HAZARDS = {"person", "bicycle", "car", "motorcycle", "bus", "truck", "dog", "cat", "horse", "cow",
           "sheep", "bird", "chair", "bench", "potted plant", "suitcase", "backpack", "umbrella",
           "fire hydrant", "stop sign", "parking meter", "dining table", "kite", "airplane"}

# Looming thresholds per world: (caution, warning). Third-person looming is a weak signal
# (best feature AUC 0.65 for impact within ~2 s, calibrated on the mock's ground truth) and
# its scale differs by world: clear forward flight on LingBot already reads 0.19-0.42.
# So looming never calls a collision on its own; the detector does that.
LOOM = {"mock": (0.13, 0.30), "reactor": (0.45, 0.70)}
PRESENCE_LOST = 0.35
# How far below the drone's box an object's base may sit and still be at the drone's depth
# (normalised image height). The drone flies at waist height, so its ground line is a little
# below its box.
GROUND_MARGIN = 0.22
PERSON_MIN_HEIGHT = 0.6  # x drone box height. Real contacts measured 0.76-1.15, background people in a crowded venue 0.43-0.44 (few examples)


VEHICLES = {"bicycle", "car", "motorcycle", "bus", "truck"}


def category(coco_label: str) -> str:
    """COCO has no post, trunk or signboard: those come back as cow, bench or hydrant.
    Report what the detector can be trusted on, and call everything else an obstacle."""
    return "person" if coco_label == "person" else "vehicle" if coco_label in VEHICLES else "obstacle"


@dataclass
class Hazard:
    label: str  # person | vehicle | obstacle
    raw: str  # the detector's own COCO label, for debugging
    conf: float
    box: tuple  # normalised x0, y0, x1, y1
    gap: float  # distance to the drone's box, in drone-widths (0 = touching)
    zone: str  # touching | close | ahead | far


@dataclass
class Assessment:
    verdict: str = "clear"
    reasons: list = field(default_factory=list)
    hazards: list = field(default_factory=list)
    presence: float = 1.0
    danger: float = 0.0
    obedience: float | None = None
    ms: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["presence"], d["danger"], d["ms"] = round(self.presence, 3), round(self.danger, 3), round(self.ms, 1)
        return d


_detector = None
_detector_lock = threading.Lock()


def load_detector():
    """Load YOLO once per process and warm it with one dummy frame. Importing ultralytics and
    the first predict take several seconds; doing that inside a flight froze the dashboard."""
    global _detector
    with _detector_lock:
        if _detector is None:
            from ultralytics import YOLO

            weights = DATA / "weights" / "yolo11n.pt"
            model = YOLO(str(weights) if weights.exists() else "yolo11n.pt")
            model.predict(np.zeros((360, 640, 3), np.uint8), imgsz=640, verbose=False)
            _detector = model
    return _detector


def _gap(a, b) -> float:
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    return float(np.hypot(dx, dy))


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class Sentinel:
    def __init__(self, spec: WorldSpec, use_detector: bool = True, kind: str = "reactor"):
        self.spec = spec
        self.loom_caution, self.loom_warn = LOOM.get(kind, LOOM["reactor"])
        x, y, w, h = spec.drone_box
        self.drone = (x, y, x + w, y + h)
        self.model = load_detector() if use_detector else None
        seed = cv2.imread(str(ASSETS / "seeds" / spec.image))
        cut = cv2.imread(str(ASSETS / "seeds" / "drone_cutout.png"), cv2.IMREAD_UNCHANGED)
        self._seed_gray = cv2.cvtColor(seed, cv2.COLOR_BGR2GRAY)
        self._alpha = cut[..., 3]
        self._streak_lost = 0
        self._streak_disobey = 0

    # ---- signals ------------------------------------------------------------------------
    def presence(self, gray: np.ndarray) -> float:
        """Best masked match of the seed's drone near its expected place (scale and drift tolerant)."""
        H, W = gray.shape[:2]
        x, y, w, h = self.spec.drone_box
        tw, th = int(w * W), int(h * H)
        seed = cv2.resize(self._seed_gray, (W, H))
        tpl = seed[int(y * H):int(y * H) + th, int(x * W):int(x * W) + tw]
        mask = (cv2.resize(self._alpha, (tw, th)) > 128).astype(np.uint8) * 255
        x0, y0 = max(0, int((x - w / 2) * W)), max(0, int((y - h / 2) * H))
        x1, y1 = min(W, int((x + w * 1.5) * W)), min(H, int((y + h * 1.5) * H))
        win = gray[y0:y1, x0:x1]
        best = 0.0
        for s in (0.85, 1.0, 1.15):
            t, m = cv2.resize(tpl, None, fx=s, fy=s), cv2.resize(mask, None, fx=s, fy=s)
            if t.shape[0] < win.shape[0] and t.shape[1] < win.shape[1]:
                r = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED, mask=m)
                best = max(best, float(np.nanmax(np.nan_to_num(r, nan=-1.0))))
        return best

    def detect(self, rgb: np.ndarray) -> list[Hazard]:
        if self.model is None:
            return []
        H, W = rgb.shape[:2]
        r = self.model.predict(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), imgsz=640, conf=0.25, verbose=False)[0]
        dw = self.drone[2] - self.drone[0]
        out = []
        for b, c, k in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist()):
            label = r.names[int(k)]
            if label not in HAZARDS:
                continue
            box = (b[0] / W, b[1] / H, b[2] / W, b[3] / H)
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            on_drone = self.drone[0] <= cx <= self.drone[2] and self.drone[1] <= cy <= self.drone[3]
            if label != "person" and (_iou(box, self.drone) > 0.2 or on_drone):
                continue  # the detector reading the drone itself as a bench, table or kite
            gap = _gap(box, self.drone) / dw
            ahead = box[3] <= self.drone[3] and self.drone[0] - dw * 0.25 <= cx <= self.drone[2] + dw * 0.25
            # Depth from the chase view: whatever stands on the ground nearer the camera has its
            # base lower in the frame. A person whose feet are well below the drone's ground
            # line is between the camera and the drone: overlapping in 2D, not touching it.
            behind = box[3] > self.drone[3] + GROUND_MARGIN
            # Size check for people: one standing at the drone's distance would be far taller than
            # the drone's box (a 1.7 m person vs a 0.35 m drone). A small person is well behind it,
            # even when a crowd hides their feet and the ground-line test cannot see them.
            far_by_size = label == "person" and (box[3] - box[1]) < PERSON_MIN_HEIGHT * (self.drone[3] - self.drone[1])
            if behind:
                zone = "behind"
            elif far_by_size:
                zone = "far"
            else:
                zone = "touching" if gap == 0 else "close" if gap < 0.5 else "ahead" if (ahead and gap < 1.5) else "far"
            out.append(Hazard(category(label), label, round(c, 2), tuple(round(v, 4) for v in box), round(gap, 2), zone))
        return out

    # ---- verdict ------------------------------------------------------------------------
    def assess(self, rgb: np.ndarray, perception=None, action: str = "hover") -> Assessment:
        t0 = time.perf_counter()
        a = Assessment()
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        a.presence = self.presence(gray)
        a.hazards = self.detect(rgb)
        a.danger = perception.danger if perception else 0.0
        a.obedience = perception.obedience if perception else None

        ranked = []  # (severity, order, reason)

        def flag(verdict: str, reason: str):
            ranked.append((SEVERITY[verdict], len(ranked), reason))
            if SEVERITY[verdict] > SEVERITY[a.verdict]:
                a.verdict = verdict

        for hz in a.hazards:
            if hz.zone == "touching":
                flag("collision", f"{hz.label} touching the drone")
            elif hz.zone == "close":
                flag("warning", f"{hz.label} within half a drone-width")
            elif hz.zone == "ahead":
                flag("warning", f"{hz.label} in the flight path")
            elif hz.zone == "behind":
                continue  # behind the drone's flight path: no risk, no call
            else:
                flag("caution", f"{hz.label} in view")
        if a.danger > self.loom_warn:
            flag("warning", f"obstacle closing fast: looming {a.danger:.2f}")
        elif a.danger > self.loom_caution:
            flag("caution", f"something ahead is getting closer: looming {a.danger:.2f}")

        self._streak_lost = self._streak_lost + 1 if a.presence < PRESENCE_LOST else 0
        if self._streak_lost >= 2:
            flag("anomaly", "drone lost: the world model dropped or morphed its subject")
        moving = action not in ("hover", "yaw_left", "yaw_right")
        self._streak_disobey = self._streak_disobey + 1 if (moving and a.obedience is not None and a.obedience < 0) else 0
        if self._streak_disobey >= 3:
            flag("anomaly", "world ignoring the controls for 3 steps")
        # Most severe first, so the first reason is always the one behind the verdict.
        a.reasons = list(dict.fromkeys(r for _, _, r in sorted(ranked, key=lambda x: (-x[0], x[1]))))  # no repeats
        a.ms = (time.perf_counter() - t0) * 1000
        return a

    def reset(self):
        self._streak_lost = self._streak_disobey = 0


class Narrator:
    """Local VLM (Ollama) describing what is around the drone, in the background.

    Called with the newest frame whenever it is free (~4-5 s per answer on a laptop GPU);
    never blocks the control loop.
    """

    def __init__(self, model: str = "qwen3-vl:4b", url: str = "http://localhost:11434/api/chat"):
        self.model, self.url = model, url
        self.latest = None  # {"text", "at", "ms"}; only ever a real sentence
        self.last_error = None  # kept for debugging, never shown as narration
        self._busy = False
        self.available = self._ping()

    def _ping(self) -> bool:
        try:
            with urllib.request.urlopen(self.url.replace("/api/chat", "/api/tags"), timeout=2) as r:
                return any(m["name"] == self.model for m in json.load(r).get("models", []))
        except Exception:
            return False

    def warm_up(self) -> None:
        """Load the model before the first flight (cold start is ~13 s on a laptop GPU)."""
        if self.available:
            self.offer(np.full((369, 640, 3), 128, np.uint8))

    def offer(self, rgb: np.ndarray) -> None:
        if not self.available or self._busy:
            return
        self._busy = True
        jpg = cv2.imencode(".jpg", cv2.cvtColor(cv2.resize(rgb, (640, 369)), cv2.COLOR_RGB2BGR))[1].tobytes()
        threading.Thread(target=self._run, args=(base64.b64encode(jpg).decode(),), daemon=True).start()

    def _run(self, b64: str) -> None:
        t0 = time.perf_counter()
        try:
            body = {"model": self.model, "stream": False, "think": False, "keep_alive": "30m",
                    # A fixed context size: with Ollama's default, qwen2.5-vl intermittently
                    # emits "@@@@..." on this 4 GB GPU; at 4096 it answered every test frame.
                    "options": {"temperature": 0, "num_predict": 120, "num_ctx": 4096},
                    "messages": [{"role": "user", "images": [b64], "content":
                                  "A small white drone is flying away from the camera in the centre of this frame. "
                                  "In one short sentence, say what is closest to the drone and whether it looks safe."}]}
            req = urllib.request.Request(self.url, json.dumps(body).encode(), {"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:  # a cold model load can take a minute
                msg = json.load(r)["message"]
            # qwen3-vl through Ollama sometimes leaves `content` empty and answers in `thinking`.
            text = (msg.get("content") or "").strip() or (msg.get("thinking") or "").strip().split("\n")[-1]
            # Under GPU memory pressure the small model sometimes emits junk ("@@@@...");
            # keep the previous sentence rather than show it.
            letters = sum(c.isalpha() or c == " " for c in text)
            if text and letters / len(text) > 0.8:
                self.latest = {"text": text[:220], "at": time.time(), "ms": round((time.perf_counter() - t0) * 1000)}
        except Exception as e:  # noqa: BLE001 - the narrator is optional colour, never a failure
            self.last_error = f"{e.__class__.__name__}: {e}"
        finally:
            self._busy = False
