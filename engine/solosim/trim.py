"""Find the useful part of a raw clip, from the pixels alone.

A capture session does not start when the task starts. The wearer switches the camera on, puts the
harness over their head, adjusts it, walks to the bench, and only then do the hands start working;
at the other end they walk away and take it off. Paying an annotator to sit through that is paying
twice for nothing, and letting them annotate it produces segments nobody wants.

There is no metadata to lean on here: no slate, no markers, no timestamps, no operator notes. So
the cut is decided from what the frames themselves show:

    hands       a head-mounted camera pointed at work has the wearer's hands in it. Putting the
                camera on has one hand very close to the lens, or no hands at all.
    head_motion mounting and walking swing the whole frame. Working does not.
    hand_motion flow that is not the camera moving: the hands actually doing something.
    blur/light  the lens is often smeared or dark while it is being handled.

The useful region is the first to the last sustained *work* (hands present and acting while the
head is reasonably steady), padded a little so nothing is clipped. Everything before and after is
dead footage. The function returns its own confidence and the reasons behind it, because a cut is
a destructive act and the QC operator has to be able to disagree with it.

QC can also narrow the cut to a subject by typing one in — "cutting pizza", "the espresso
machine". That runs CLIP over the sampled frames and keeps only the stretch where the subject is
actually on camera, so a thirty-minute kitchen shift becomes the four minutes the client asked
for. The honest limit of it is written over `topic_scores`: it finds where a thing is *visible*,
not where the task about it happens, so the prompt narrows the work mask rather than replacing it.
"""
from dataclasses import dataclass, field

import cv2
import numpy as np

from .clip_io import Clip

RATE = 2.0  # samples/s: enough to find a boundary, cheap enough to run before anything else
PAD = 1.0  # seconds kept on each side of the first/last work, so nothing is clipped
MIN_RUN = 1.5  # a stretch of work this long counts as the task starting
BRIDGE = 2.5  # work pauses (reaching, looking) shorter than this do not end the useful part
FLOOR = 0.25  # "busy" means at least this share of the clip's own peak hand activity
WHIP = 0.9  # head motion (frame-widths/s) above this is mounting or walking, not working
MIN_KEEP = 3.0  # never propose a clip shorter than this
MAX_CUT_SHARE = 0.6  # refuse to cut away more than this much of the clip without a human saying so
TOPIC_BRIDGE = 3.0  # the subject leaving frame for less than this does not end the useful part
TOPIC_MIN_RUN = 1.0  # the subject has to hold on camera this long: one frame is a recogniser fluke

# What a frame with nothing in it looks like. The operator's prompt is scored against these rather
# than on its own, because a raw CLIP similarity has no absolute scale: 0.27 means nothing until you
# know what the alternatives scored. Asking "more like cutting pizza, or more like an empty counter?"
# gives a number that is comparable across clips and across prompts.
AWAY = [
    "an empty room with nobody in it",
    "a blurry photo of nothing in particular",
    "a view of the floor",
    "a view of the ceiling",
    "a person walking down a corridor",
    "a hand covering the camera lens",
    "a close-up of a wall",
]


@dataclass
class Trim:
    start: float
    end: float
    duration: float  # of the original
    confidence: float  # 0-1, how sure the gate is about this cut
    head_dead: float  # seconds of dead footage at the front
    tail_dead: float
    reasons: list[str] = field(default_factory=list)
    auto: bool = True  # safe to apply without asking
    topic: str = ""  # the subject QC asked to narrow to, if any
    topic_share: float = 0.0  # share of the original clip where that subject was on camera

    def as_dict(self) -> dict:
        return {"start": round(self.start, 2), "end": round(self.end, 2), "duration": round(self.duration, 2),
                "kept": round(self.end - self.start, 2), "confidence": round(self.confidence, 2),
                "head_dead": round(self.head_dead, 2), "tail_dead": round(self.tail_dead, 2),
                "cut_share": round(1 - (self.end - self.start) / max(0.01, self.duration), 3),
                "reasons": self.reasons, "auto": self.auto,
                "topic": self.topic, "topic_share": round(self.topic_share, 3)}


def scan(clip: Clip, rate: float = RATE, progress=None, embed: bool = False) -> dict:
    """One cheap decode pass: hands, motion and exposure, and the CLIP embedding if asked for.

    The embedding rides along on the decode that was happening anyway, and is kept with the rest of
    the scan, so QC can retype the prompt and re-scope the cut without touching the video again.
    """
    from .signals import _yolo

    hand = _yolo("hand_yolov8n.pt")
    enc = _encoder() if embed else None
    frames: list = []
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST)
    cap = cv2.VideoCapture(str(clip.video))
    step = max(1, int(round(clip.fps / rate)))
    t, hands, hand_area, head, act, blur, bright = [], [], [], [], [], [], []
    prev = None
    i = 0
    while True:
        if not cap.grab():
            break
        if i % step == 0:
            ok, bgr = cap.retrieve()
            if not ok:
                break
            H, W = bgr.shape[:2]
            g = cv2.cvtColor(cv2.resize(bgr, (320, max(1, int(320 * H / W))), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            t.append(i / clip.fps)
            blur.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
            bright.append(float(g.mean()))
            small = cv2.resize(g, (160, max(1, int(160 * H / W))), interpolation=cv2.INTER_AREA)
            if prev is not None:
                f = dis.calc(prev, small, None)
                med = np.median(f.reshape(-1, 2), axis=0)
                head.append(float(np.hypot(*med)) * rate / small.shape[1])
                act.append(float(np.linalg.norm(f - med, axis=2).mean()) * rate / small.shape[1])
            else:
                head.append(0.0)
                act.append(0.0)
            prev = small
            r = hand.predict(bgr, imgsz=480, conf=0.25, verbose=False)[0]
            boxes = r.boxes.xyxy.tolist()
            hands.append(len(boxes))
            # How much of the frame the hands fill: a hand over the lens while the camera is being
            # put on fills far more of it than hands working at arm's length.
            hand_area.append(max((abs((b[2] - b[0]) * (b[3] - b[1])) / (W * H) for b in boxes), default=0.0))
            if enc is not None:
                frames.append(enc["prep"](enc["pil"].fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))))
            if progress and len(t) % 40 == 0:
                progress(f"looking for the useful part ({t[-1]:.0f}s of {clip.duration:.0f}s)", t[-1] / max(1, clip.duration))
        i += 1
    cap.release()
    out = {k: np.asarray(v, np.float32) for k, v in
           {"t": t, "hands": hands, "hand_area": hand_area, "head_motion": head, "hand_motion": act,
            "blur": blur, "bright": bright}.items()}
    if enc is not None and frames:
        if progress:
            progress("recognising what is in the frames", 0.9)
        out["emb"] = _encode_frames(enc, frames)
    return out


def _encoder():
    """CLIP ViT-B/32 on the CPU, or None if it is not installed.

    The weights are cached on disk after the first load, so this needs no network and costs nothing
    per clip — which is the whole reason the prompt scoping is done this way and not by asking a
    hosted vision model about every frame.
    """
    try:
        import clip as openai_clip
        import torch
        from PIL import Image
    except Exception:
        return None
    model, prep = openai_clip.load("ViT-B/32", device="cpu")
    model.eval()
    return {"model": model, "prep": prep, "torch": torch, "clip": openai_clip, "pil": Image}


def _encode_frames(enc, frames: list, batch: int = 32) -> np.ndarray:
    torch = enc["torch"]
    out = []
    with torch.no_grad():
        for i in range(0, len(frames), batch):
            v = enc["model"].encode_image(torch.stack(frames[i:i + batch])).float()
            out.append((v / v.norm(dim=-1, keepdim=True)).numpy())
    return np.concatenate(out).astype(np.float32)


def topic_scores(emb: np.ndarray, prompt: str, enc=None) -> np.ndarray | None:
    """Per-frame margin between "this looks like what QC asked for" and "this looks like nothing".

    A raw CLIP similarity is useless on its own: 0.27 for "a pizza" means nothing until you know
    that an empty corridor also scores 0.24. So every frame is scored against the prompt *and*
    against `AWAY`, and what comes back is the difference. Above zero the frame looks more like the
    subject than like any way of being empty; below zero it does not. Measured on a kitchen clip,
    subjects that are really there sit at +0.006 to +0.044 mean margin and subjects that are not
    (a bicycle, a horse) sit negative — a separation a plain similarity does not give you.

    The limit of it, which matters for how far this can be trusted: it finds where a thing is
    *visible*, not where the task about it happens. A pizza sitting untouched on a counter scores
    as well as a pizza being cut. That is why `find` intersects this with the hand-work mask rather
    than trusting it alone — the kept region is where the subject is on camera *and* hands are
    working on it.
    """
    enc = enc or _encoder()
    if enc is None or emb is None or not len(emb):
        return None
    torch = enc["torch"]
    p = prompt.strip()
    # Three phrasings, best one wins: CLIP is sensitive to wording, and which phrasing lands is not
    # something a QC operator should have to guess at.
    texts = [f"a first-person photo of {p}", f"a photo of {p}", p] + AWAY
    with torch.no_grad():
        tf = enc["model"].encode_text(enc["clip"].tokenize(texts, truncate=True)).float()
        tf = (tf / tf.norm(dim=-1, keepdim=True)).numpy()
    sim = emb @ tf.T
    return (sim[:, :3].max(axis=1) - sim[:, 3:].max(axis=1)).astype(np.float32)


def _runs(mask: np.ndarray, t: np.ndarray, min_len: float) -> list[tuple[int, int]]:
    out, s = [], None
    for i, b in enumerate(np.append(mask, False)):
        if b and s is None:
            s = i
        elif not b and s is not None:
            if t[i - 1] - t[s] >= min_len:
                out.append((s, i - 1))
            s = None
    return out


def _otsu(x: np.ndarray, bins: int = 64) -> float:
    """The natural split in a set of values, by Otsu's method.

    Needed because "is the subject on camera" has no threshold that travels between clips. Scoring
    the prompt against `AWAY` tells you whether the subject is in the clip at all, but every frame
    of a busy kitchen beats "an empty room", so a fixed cutoff keeps the whole shift. Otsu finds the
    gap in *this* clip's own scores instead: where the subject comes and goes the scores are
    two-humped and the split lands in the valley between them, and where the subject is simply
    always there the distribution is one hump and the split sits low and keeps nearly all of it.
    Both of those are the right answer, which a constant could not be for both.
    """
    lo, hi = float(x.min()), float(x.max())
    if hi - lo < 1e-9:
        return lo
    h, edges = np.histogram(x, bins=bins, range=(lo, hi))
    w = h.astype(np.float64) / h.sum()
    mid = (edges[:-1] + edges[1:]) / 2
    cw = np.cumsum(w)
    cm = np.cumsum(w * mid)
    total = cm[-1]
    ok = (cw > 1e-9) & (cw < 1 - 1e-9)
    if not ok.any():
        return lo
    between = np.where(ok, (total * cw - cm) ** 2 / np.clip(cw * (1 - cw), 1e-12, None), -np.inf)
    return float(edges[1:][int(np.argmax(between))])


def _mask(runs: list[tuple[int, int]], n: int) -> np.ndarray:
    """Back from run indices to a boolean mask."""
    out = np.zeros(n, bool)
    for a, b in runs:
        out[a:b + 1] = True
    return out


def _bridge(mask: np.ndarray, t: np.ndarray, gap: float) -> np.ndarray:
    """Fill gaps shorter than `gap` between True stretches."""
    out = mask.copy()
    on = np.flatnonzero(mask)
    if on.size < 2:
        return out
    for a, b in zip(on[:-1], on[1:]):
        if b - a > 1 and t[b] - t[a] <= gap:
            out[a:b] = True
    return out


def _dead(s: dict, act: np.ndarray, head: np.ndarray, thr: float) -> np.ndarray:
    """Frames with nothing worth annotating in them, on their own terms.

    Work is a strong claim: hands in frame, acting, camera steady. Dead is a much weaker one, and
    the trim is decided by *dead*, not by *work* — cutting a quiet second of real work costs the
    client a labelled action, while keeping a quiet second of mounting costs an annotator a glance.
    """
    quiet = (act <= thr) & (s["hands"] < 1)
    swinging = head > WHIP
    # Near-absolute, not relative to the clip: real work is often heavily motion-blurred, and a
    # threshold set off the clip mean throws those frames away too. This catches a flat or black
    # frame — a covered lens, a camera pointed at the floor, a fade — and nothing else.
    unusable = (s["blur"] < 1.5) | (s["bright"] < 25)
    return quiet | (swinging & (s["hands"] < 1)) | (unusable & (s["hands"] < 1))


def _expand(dead: np.ndarray, i: int, step: int) -> int:
    """Walk outward from a work run until the footage really is dead, and stop there."""
    j = i
    while 0 <= j + step < len(dead) and not dead[j + step]:
        j += step
    return j


def find(clip: Clip, s: dict, topic: str = "") -> Trim:
    """Where the work starts and stops. Decided from the frames, with a confidence.

    `topic` narrows the answer to a subject the QC operator typed in. It never widens it: a prompt
    can only take more footage away, so a bad prompt costs a re-cut and never smuggles dead footage
    through to the annotators.
    """
    t = s["t"]
    dur = float(clip.duration)
    topic = (topic or "").strip()
    if len(t) < 4:
        return Trim(0.0, dur, dur, 0.0, 0.0, 0.0, ["clip too short to scan"], auto=False, topic=topic)

    k = np.ones(3) / 3
    act = np.convolve(s["hand_motion"], k, mode="same")
    head = np.convolve(s["head_motion"], k, mode="same")
    # The floor is a fraction of this clip's own peak, not a percentile of every sample. A percentile
    # is pulled upward by the dead footage it is meant to find: on a clip that is half mounting and
    # walking, the median sits inside the real work and cuts most of it away.
    busy = act > max(FLOOR * float(np.percentile(act, 90)), 1e-6)  # same threshold as _dead
    steady = head < WHIP
    present = s["hands"] > 0
    # A hand filling more than a third of the frame is the wearer handling the camera, not working.
    handling = s["hand_area"] > 0.33
    work = busy & steady & present & ~handling

    # Working hands drop out of frame constantly — reaching for a drawer, turning to look. Bridging
    # those pauses means the useful part is one region, not a string of fragments.
    work = _bridge(work, t, BRIDGE)

    topic_share, on_topic = 0.0, None
    if topic:
        m = topic_scores(s.get("emb"), topic)
        if m is None or not len(m):
            return Trim(0.0, dur, dur, 0.1, 0.0, 0.0,
                        [f"could not look for “{topic}”: the subject recogniser is not available"],
                        auto=False, topic=topic)
        # Is the subject in this clip at all? The 90th percentile of the margin answers that at the
        # whole-clip level, and it is the gate that stops a wrong prompt producing a confident wrong
        # cut: on a kitchen clip it is positive for the pizza and the oven, negative for a bicycle.
        # When it is negative the honest move is to keep everything and let QC look, because cutting
        # to wherever the recogniser happened to twitch is worse than not cutting at all.
        if float(np.percentile(m, 90)) <= 0.0:
            return Trim(0.0, dur, dur, 0.1, 0.0, 0.0,
                        [f"“{topic}” does not appear to be in this clip — keeping all of it rather than cutting to a guess"],
                        auto=False, topic=topic, topic_share=float((m > 0).mean()))
        # Where in *this* clip the subject is, as opposed to merely whether it is here: the split in
        # the clip's own margins, floored at zero so a cut never keeps frames that lost to `AWAY`.
        cut_at = max(_otsu(m), 0.0)
        # A single frame over the line is the recogniser twitching; a subject really on camera holds
        # for seconds. Hold first, then bridge, so brief occlusions join up but flukes never do.
        seen = _bridge(_mask(_runs(m >= cut_at, t, TOPIC_MIN_RUN), len(t)), t, TOPIC_BRIDGE)
        topic_share = float(seen.mean())
        blocks = _runs(seen, t, TOPIC_MIN_RUN)
        if topic_share < 0.02 or not blocks:
            return Trim(0.0, dur, dur, 0.1, 0.0, 0.0,
                        [f"“{topic}” never stays on camera long enough to cut to — keeping the whole clip"],
                        auto=False, topic=topic, topic_share=topic_share)
        # The prompt picks the window, not the frames. Keeping only the frames the recogniser liked
        # would shred a continuous task into the seconds where the subject happened to face the lens
        # and throw away the reach for it and the putting of it down — which are the parts a robot
        # has to learn. So the longest block where the subject is around becomes the region of
        # interest, and the ordinary dead-footage trim then runs inside it.
        i0, i1 = max(blocks, key=lambda r: t[r[1]] - t[r[0]])
        on_topic = _mask([(i0, i1)], len(t))
        work = work & on_topic

    runs = _runs(work, t, MIN_RUN)
    if not runs:  # nothing looked like work: keep everything and say so
        miss = (f"no sustained hand work on “{topic}” found — keeping the whole clip" if topic
                else "no sustained hand work found — keeping the whole clip")
        return Trim(0.0, dur, dur, 0.15, 0.0, 0.0, [miss], auto=False,
                    topic=topic, topic_share=topic_share)

    thr = max(FLOOR * float(np.percentile(act, 90)), 1e-6)
    dead = _dead(s, act, head, thr)
    if on_topic is not None:
        # Footage without the subject in it is dead *for this request*, however busy the hands are.
        # Without this the boundary walk steps straight out of the topic region to the clip edges.
        dead = dead | ~on_topic
    a = max(0.0, float(t[_expand(dead, runs[0][0], -1)]) - PAD)
    b = min(dur, float(t[_expand(dead, runs[-1][1], 1)]) + PAD)
    if b - a < MIN_KEEP:
        return Trim(0.0, dur, dur, 0.2, 0.0, 0.0, ["the working part is too short to trust — keeping the whole clip"],
                    auto=False, topic=topic, topic_share=topic_share)

    head_dead, tail_dead = a, dur - b
    reasons, score = [], 0.55
    if topic:
        reasons.append(f"“{topic}” is on camera for {topic_share:.0%} of the clip; the cut keeps the "
                       f"stretch where it is both visible and being handled")
        # A prompt that matches a clean, contiguous slice is a prompt that was understood. One that
        # matches scattered half-seconds everywhere is not, and should not be trusted as far.
        score += 0.1 if 0.05 <= topic_share <= 0.9 else -0.1

    # Each piece of evidence that the dead part really is dead raises the confidence.
    if head_dead > 0.5:
        pre = t < a
        if pre.any():
            if float(np.mean(s["head_motion"][pre])) > float(np.mean(s["head_motion"][~pre])) * 1.4:
                reasons.append(f"the first {head_dead:.0f}s swings around: the camera is being put on or carried")
                score += 0.15
            if float(np.mean(s["hands"][pre])) < 0.4:
                reasons.append(f"no hands at work in the first {head_dead:.0f}s")
                score += 0.1
            if float(np.mean(s["hand_area"][pre])) > 0.33:
                reasons.append("a hand covers the lens at the start: the camera is being adjusted")
                score += 0.1
            if float(np.mean(s["blur"][pre])) < float(np.mean(s["blur"][~pre])) * 0.6:
                reasons.append("the opening frames are smeared")
                score += 0.05
    if tail_dead > 0.5:
        post = t > b
        if post.any():
            if float(np.mean(s["hands"][post])) < 0.4:
                reasons.append(f"the last {tail_dead:.0f}s has no hands in frame: the session is over")
                score += 0.1
            elif float(np.mean(s["head_motion"][post])) > WHIP:
                reasons.append(f"the last {tail_dead:.0f}s is walking away")
                score += 0.08
    if not reasons:
        reasons.append("the hands work steadily from start to end: nothing worth cutting")

    # Long, uninterrupted work inside the kept region is itself evidence the boundaries are right.
    inside = (t >= a) & (t <= b)
    if inside.any() and float(work[inside].mean()) > 0.35:
        score += 0.1

    cut_share = 1 - (b - a) / dur
    auto = True
    if cut_share > MAX_CUT_SHARE and not topic:
        reasons.append(f"this would remove {cut_share:.0%} of the clip — confirm before cutting")
        score -= 0.2
        auto = False
    elif cut_share > MAX_CUT_SHARE:
        # Removing most of the clip is the point of a prompt, not a warning sign. It is still said
        # out loud, and QC still has to press send before an annotator ever sees it.
        reasons.append(f"removes {cut_share:.0%} of the clip, which is what narrowing to “{topic}” asks for")
    return Trim(a, b, dur, float(np.clip(score, 0.05, 0.95)), head_dead, tail_dead, reasons, auto,
                topic=topic, topic_share=topic_share)


def apply(clip: Clip, start: float, end: float) -> bool:
    """Cut the video to [start, end] and shift any existing segments. Returns False if ffmpeg is absent."""
    import json
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        return False
    src = clip.dir / "video.mp4"
    tmp = clip.dir / "trimmed.mp4"
    cmd = ["ffmpeg", "-y", "-ss", f"{max(0.0, start):.3f}", "-to", f"{end:.3f}", "-i", str(src),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", "-an", str(tmp)]
    if subprocess.run(cmd, capture_output=True).returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False
    # The original is kept so a cut is reversible. On a second cut — QC overriding the proposal —
    # raw.mp4 already holds the footage as it arrived, and that is what must survive, not the
    # intermediate the gate produced.
    raw = clip.dir / "raw.mp4"
    if raw.exists():
        src.unlink()
    else:
        src.replace(raw)
    tmp.replace(src)
    (clip.dir / "signals.npz").unlink(missing_ok=True)  # measured against the old timeline
    p = clip.dir / "annotations.json"
    ann = json.loads(p.read_text(encoding="utf-8"))
    kept = []
    for seg in ann.get("segments", []):
        a, b = max(seg["start"], start) - start, min(seg["end"], end) - start
        if b - a > 0.1:
            kept.append({**seg, "start": round(a, 2), "end": round(b, 2)})
    ann["segments"] = kept
    ann["trim"] = {"start": round(start, 2), "end": round(end, 2), "original_duration": round(clip.duration, 2)}
    p.write_text(json.dumps(ann, indent=1), encoding="utf-8")
    return True
