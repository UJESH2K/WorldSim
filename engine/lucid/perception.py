"""Cheap, model-free perception from optical flow. Runs at hundreds of Hz on a laptop CPU.

Three signals, all derived from dense Farneback flow between consecutive chunk frames:

* ego-motion  - an affine fit of the flow field: divergence (forward/back), mean u/v
                (yaw/strafe, climb/descend), curl (roll).
* looming     - per-cell divergence on a 3x3 grid. For a forward-moving camera the local
                divergence of a surface is ~2/time-to-contact, so a hot centre cell means
                something is about to fill the view (the insect looming reflex).
* obedience   - cosine agreement between the flow signature the commanded action *should*
                produce and the one that was measured. A world model that ignored the
                control scores low, and those frames are kept out of training.
"""
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from .actions import SIGNATURES

TRANSLATING = ("forward", "arc_left", "arc_right")

SIZE = (160, 96)  # (W, H) working resolution for flow
_STEP = 4  # subsample stride for the least-squares fits


def prep(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return cv2.resize(gray, SIZE, interpolation=cv2.INTER_AREA)


_dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)


def dense_flow(prev: np.ndarray, cur: np.ndarray) -> np.ndarray:
    # DIS rather than Farneback: a 10 degree yaw is a ~15 px shift at this resolution, which
    # Farneback silently reports as ~0 while DIS recovers it.
    return _dis.calc(prev, cur, None)


def _grid(h: int, w: int):
    ys, xs = np.mgrid[0:h:_STEP, 0:w:_STEP].astype(np.float32)
    half = w / 2.0
    return (xs - w / 2.0) / half, (ys - h / 2.0) / half, half


def _affine(u, v, x, y):
    """Least-squares fit u = a0 + a1 x + a2 y, v = b0 + b1 x + b2 y."""
    A = np.stack([np.ones_like(x), x, y], axis=1)
    (a, *_), (b, *_) = np.linalg.lstsq(A, u, rcond=None), np.linalg.lstsq(A, v, rcond=None)
    resid = np.sqrt(np.mean((A @ a - u) ** 2 + (A @ b - v) ** 2))
    return a, b, float(resid)


@dataclass
class Perception:
    div: float = 0.0
    sx: float = 0.0  # horizontal stretch du/dx
    sy: float = 0.0  # vertical stretch dv/dy
    u: float = 0.0
    v: float = 0.0
    curl: float = 0.0
    mag: float = 0.0
    coherence: float = 0.0
    cells: list = field(default_factory=list)  # 3x3 local divergence, row-major
    left_flow: float = 0.0
    right_flow: float = 0.0
    danger: float = 0.0
    obedience: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def perceive(prev: np.ndarray, cur: np.ndarray, action: str, mask: tuple | None = None) -> Perception:
    """`mask` = normalised (x, y, w, h) box excluded from every fit: in third person the drone
    is pinned to the centre of the frame, so its pixels read as "no motion" and would drown
    out the obstacles appearing right around it."""
    fl = dense_flow(prev, cur)
    h, w = prev.shape
    x, y, half = _grid(h, w)
    sub = fl[0:h:_STEP, 0:w:_STEP] / half
    u, v = sub[..., 0], sub[..., 1]
    ok = np.ones(u.shape, bool)
    if mask is not None:
        mx, my, mw, mh = mask
        gx = (x * half + w / 2.0) / w  # back to normalised image coordinates
        gy = (y * half + h / 2.0) / h
        ok = ~((gx >= mx) & (gx <= mx + mw) & (gy >= my) & (gy <= my + mh))

    a, b, resid = _affine(u[ok], v[ok], x[ok], y[ok])
    mag = float(np.sqrt(np.mean(u[ok] ** 2 + v[ok] ** 2)))
    p = Perception(
        div=float(a[1] + b[2]),
        sx=float(a[1]),
        sy=float(b[2]),
        u=float(a[0]),
        v=float(b[0]),
        curl=float(b[1] - a[2]),
        mag=mag,
        coherence=float(max(0.0, 1.0 - resid / (mag + 1e-6))),
    )

    gh, gw = u.shape
    cells = []
    for r in range(3):
        for c in range(3):
            rs, cs = slice(r * gh // 3, (r + 1) * gh // 3), slice(c * gw // 3, (c + 1) * gw // 3)
            k = ok[rs, cs]
            if k.sum() < 12:  # cell is mostly the masked drone
                cells.append(0.0)
                continue
            ca, cb, _ = _affine(u[rs, cs][k], v[rs, cs][k], x[rs, cs][k], y[rs, cs][k])
            cells.append(float(ca[1] + cb[2]))
    p.cells = [round(c, 4) for c in cells]

    # Lateral flow balance over the upper two thirds (the bottom third is mostly ground).
    # The global shift is removed first so a turn does not bias one side.
    upper = np.zeros_like(ok)
    upper[: 2 * gh // 3] = True
    left, right = upper.copy(), upper.copy()
    left[:, gw // 3:] = False
    right[:, : gw - gw // 3] = False
    tu, tv = u - p.u, v - p.v
    p.left_flow = float(np.mean(np.hypot(tu[left & ok], tv[left & ok])))
    p.right_flow = float(np.mean(np.hypot(tu[right & ok], tv[right & ok])))
    # Danger: looming in the centre column above the ground band. Divergence is unchanged
    # by rotation, so it is valid whenever the camera is translating forward, arcs included.
    p.danger = float(max(cells[1], cells[4])) if action in TRANSLATING else 0.0
    p.obedience = obedience(action, p)
    return p


def subject_presence(ref: np.ndarray, cur: np.ndarray, box: tuple) -> float:
    """Normalised cross-correlation of the subject's box against the seed image's.

    A world model can quietly drop, duplicate or morph its subject; a third-person drone
    that stops looking like the drone means the dream broke, whatever the critic says.
    Inputs are grayscale frames of any (equal-aspect) size.
    """
    def crop(img):
        h, w = img.shape[:2]
        x, y, bw, bh = box
        patch = img[int(y * h):int((y + bh) * h), int(x * w):int((x + bw) * w)].astype(np.float32)
        return cv2.resize(patch, (64, 32), interpolation=cv2.INTER_AREA)

    a, b = crop(ref), crop(cur)
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6))


def obedience(action: str, p: Perception) -> float:
    """+1 when the measured motion matches the commanded action, -1 when it is opposite."""
    measured = np.array([p.sx, p.sy, p.u, p.v])
    norm = float(np.linalg.norm(measured))
    if action == "hover":
        return float(np.clip(1.0 - norm / 0.05, -1.0, 1.0))
    if norm < 0.01:
        return -0.5  # commanded motion, got a still frame
    expected = np.array(SIGNATURES[action])
    return float(np.dot(expected, measured) / (np.linalg.norm(expected) * norm))
