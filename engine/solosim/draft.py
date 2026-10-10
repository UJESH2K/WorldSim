"""AI first pass: annotate raw footage so a person verifies instead of starting from nothing.

Segments come from the measured hand/object activity: runs of activity above the clip's own
threshold, merged across short pauses and split when they run long. The AI reviewer then names
each one (verb + object) without being told anything.

Every drafted segment carries a **confidence**, because a claim nobody can calibrate is worse than
no claim. The confidence is not the model's opinion alone - a vision model asked "how sure are
you?" is a poor judge of itself. It combines what the model says with what the pixels support:

    model       the reviewer's own confidence in the name it gave
    hands       were the hands actually visible while this was happening
    activity    how far above the clip's own noise floor the motion was
    sharpness   a smeared segment is a guess however confident the model sounds
    edges       activity that dies away cleanly at both ends is a real boundary

Low confidence is not a defect, it is a routing decision: it tells the annotator where to look
first, and it tells the gate which claims to put in front of a human before anything ships.
"""
import json
import os
import time
import urllib.error
import urllib.request

import numpy as np

from . import checks, vlm
from .clip_io import Clip, Segment

MIN_S, MAX_S, MERGE_S = 0.8, 6.0, 0.6


def segments_from_activity(sig: dict) -> list[tuple[float, float]]:
    t = sig["t"]
    act, on, _ = checks._activity(sig)
    busy = act > on
    runs, s = [], None
    for i, b in enumerate(np.append(busy, False)):
        if b and s is None:
            s = i
        elif not b and s is not None:
            runs.append([float(t[s]), float(t[i - 1])])
            s = None
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] < MERGE_S:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        if b - a < MIN_S:
            continue
        n = int(np.ceil((b - a) / MAX_S))
        edges = np.linspace(a, b, n + 1)
        out += [(round(float(edges[k]), 2), round(float(edges[k + 1]), 2)) for k in range(n)]
    return out


NAME_SCHEMA = {"type": "object", "properties": {"verb": {"type": "string"}, "object": {"type": "string"},
                                                "action": {"type": "string"}, "confidence": {"type": "number"}},
               "required": ["verb", "object", "action", "confidence"], "additionalProperties": False}
ASK = ("Name the single action the camera wearer's hands perform, as an annotator would: a verb and its object, "
       "at most 5 words, lower case. Give your confidence from 0 to 1: 1 when the frames show the action "
       "unmistakably, below 0.5 when you are guessing from partial or unclear evidence.")


def _name_claude(clip: Clip, a: float, b: float) -> str:
    import anthropic

    g = Segment(id="draft", start=a, end=b, verb="", noun="", narration="")
    _, sheet = vlm.contact_sheet(clip, g, cell=320)
    r = anthropic.Anthropic().messages.create(
        model=vlm.BULK_MODEL, max_tokens=1000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": NAME_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Six frames in time order (left to right, then top to bottom) from a head-mounted camera."},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": sheet}},
            {"type": "text", "text": ASK}]}])
    vlm._charge(r.usage, f"draft {clip.id} {a:.1f}-{b:.1f}", vlm.BULK_MODEL)
    if r.stop_reason == "refusal":
        return "unnamed action", 0.0
    d = json.loads(next(x.text for x in r.content if x.type == "text"))
    name = (d.get("action") or f"{d.get('verb', '')} {d.get('object', '')}").strip().lower() or "unnamed action"
    return name, float(d.get("confidence") or 0.5)


def _name(clip: Clip, a: float, b: float) -> tuple[str, float]:
    if vlm.backend() == "haiku":
        try:
            return _name_claude(clip, a, b)
        except Exception as e:  # noqa: BLE001 - fall back to Groq
            print(f"draft naming failed: {e!r}"[:200])
    if not os.environ.get("GROQ_API_KEY"):
        return "unnamed action", 0.0
    g = Segment(id="draft", start=a, end=b, verb="", noun="", narration="")
    _, sheet = vlm.contact_sheet(clip, g)
    content = [{"type": "text", "text": "Six frames in time order (left to right, then top to bottom) from a head-mounted camera."},
               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sheet}"}},
               {"type": "text", "text": "Name the single action the camera wearer's hands perform, as an annotator would: a verb and "
                                        'its object, at most 5 words, plus your confidence from 0 to 1. Reply with JSON only: '
                                        '{"verb": "...", "object": "...", "action": "...", "confidence": 0.0}'}]
    body = {"model": vlm.GROQ_MODEL, "max_tokens": 120, "temperature": 0, "reasoning_effort": "none",
            "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}", "Content-Type": "application/json",
                                  "User-Agent": "solosim/0.1"})
    for attempt in range(3):
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=60).read())
            d = json.loads(r["choices"][0]["message"]["content"])
            name = (d.get("action") or f"{d.get('verb', '')} {d.get('object', '')}").strip().lower() or "unnamed action"
            return name, float(d.get("confidence") or 0.5)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                break
            time.sleep(float(e.headers.get("retry-after") or (2 + 3 * attempt)) + 0.5)
        except (ValueError, KeyError):
            break
    return "unnamed action", 0.0


def evidence(sig: dict, a: float, b: float) -> dict:
    """What the pixels say about a drafted span, independent of what the model called it."""
    t = sig["t"]
    act, on, off = checks._activity(sig)
    w = (t >= a) & (t <= b)
    if not w.any():
        return {"hands_visible": 0.0, "activity": 0.0, "sharp": 0.0, "clean_edges": 0.0}
    idx = np.flatnonzero(w)
    hands = float((~np.isnan(sig["hands"][idx, 0, 0])).mean())
    inside = float(act[idx].mean())
    # How far above the clip's own quiet level this span sits: 0 at the floor, 1 well clear of it.
    lift = float(np.clip((inside - off) / max(1e-6, on - off), 0, 1.5)) / 1.5
    sharp = float((sig["blur"][idx] >= checks.BLUR_MIN).mean())
    # A real action is quieter just outside its boundaries than inside them.
    before = act[(t >= a - 0.8) & (t < a)]
    after = act[(t > b) & (t <= b + 0.8)]
    out = np.concatenate([x for x in (before, after) if len(x)]) if (len(before) or len(after)) else np.array([inside])
    edges = float(np.clip(1 - out.mean() / max(1e-6, inside), 0, 1))
    return {"hands_visible": round(hands, 2), "activity": round(lift, 2), "sharp": round(sharp, 2),
            "clean_edges": round(edges, 2)}


def confidence(model_conf: float, ev: dict) -> tuple[float, str]:
    """One number the annotator can sort by, and one line saying why it is what it is."""
    score = (0.40 * float(np.clip(model_conf, 0, 1))
             + 0.25 * ev["hands_visible"]
             + 0.15 * ev["activity"]
             + 0.10 * ev["sharp"]
             + 0.10 * ev["clean_edges"])
    weakest = min(("the model was unsure of the name", float(np.clip(model_conf, 0, 1))),
                  ("the hands were often out of frame", ev["hands_visible"]),
                  ("the motion barely rises above the clip's noise", ev["activity"]),
                  ("most of these frames are blurred", ev["sharp"]),
                  ("the action does not start or stop cleanly", ev["clean_edges"]), key=lambda x: x[1])
    why = "clear hands, steady motion, confident name" if score >= 0.75 else weakest[0]
    return round(float(np.clip(score, 0, 1)), 2), why


def draft(clip: Clip, sig: dict, progress=None) -> list[Segment]:
    """Annotate a clip from scratch. Every segment is a claim with a confidence attached."""
    spans = segments_from_activity(sig)
    segs = []
    for i, (a, b) in enumerate(spans):
        name, model_conf = _name(clip, a, b)
        ev = evidence(sig, a, b)
        conf, why = confidence(model_conf, ev)
        parts = name.split()
        segs.append(Segment(id=f"ai-{i:03d}", start=a, end=b, verb=parts[0] if parts else "", noun=" ".join(parts[1:]),
                            narration=name, meta={"drafted_by": "ai", "confidence": conf, "why": why,
                                                  "model_confidence": round(float(np.clip(model_conf, 0, 1)), 2),
                                                  "evidence": ev, "verified": False}))
        if progress:
            progress(f"AI first pass: named {i + 1}/{len(spans)} segments", (i + 1) / max(1, len(spans)))
    clip.save_segments(segs)
    return segs


def summary(segs: list[Segment]) -> dict:
    """How much of this draft a person should expect to change."""
    cs = [float(g.meta.get("confidence", 0)) for g in segs if g.meta.get("drafted_by") == "ai"]
    if not cs:
        return {"drafted": 0}
    arr = np.asarray(cs)
    return {"drafted": len(cs), "mean_confidence": round(float(arr.mean()), 2),
            "high": int((arr >= 0.75).sum()), "medium": int(((arr >= 0.5) & (arr < 0.75)).sum()),
            "low": int((arr < 0.5).sum())}
