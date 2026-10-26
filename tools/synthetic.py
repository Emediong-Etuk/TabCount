"""Synthetic tablet-image generator with known ground truth.

Used for unit tests and as a secondary evaluation set. Results on these images
must always be reported as *synthetic*, separately from real photos.

Everything is deterministic given a seed (numpy Generator).
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

CANVAS_W, CANVAS_H = 1200, 900

# Tablet colours (BGR). Light set is for dark backgrounds, dark set for light ones.
LIGHT_TABLET_COLORS = [
    (245, 245, 245),  # white
    (225, 235, 240),  # off-white
    (90, 220, 245),   # yellow
    (180, 170, 250),  # pink
    (90, 170, 250),   # orange
    (230, 210, 170),  # light blue
]
DARK_TABLET_COLORS = [
    (40, 40, 170),    # red
    (150, 70, 30),    # blue
    (30, 80, 140),    # brown
    (50, 120, 40),    # green
    (20, 90, 200),    # dark orange
    (110, 50, 110),   # purple
]


@dataclass
class Tablet:
    cx: float
    cy: float
    a: float            # semi-major axis (px)
    b: float            # semi-minor axis (px)
    angle: float        # degrees
    color: tuple[int, int, int]
    score_line: bool = False


@dataclass
class Scene:
    tablets: list[Tablet] = field(default_factory=list)
    background: str = "dark"          # "dark" | "light"
    bg_color: tuple[int, int, int] = (40, 40, 40)
    width: int = CANVAS_W
    height: int = CANVAS_H


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _ellipse_rho(t: Tablet, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """Normalised elliptical radius (0 at centre, 1 on the rim) over a crop."""
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    th = math.radians(t.angle)
    dx, dy = xs - t.cx, ys - t.cy
    u = dx * math.cos(th) + dy * math.sin(th)
    v = -dx * math.sin(th) + dy * math.cos(th)
    return np.sqrt((u / t.a) ** 2 + (v / t.b) ** 2), u, v


def render_scene(scene: Scene, rng: np.random.Generator | None = None,
                 degrade: bool = True, shadow: bool | None = None) -> np.ndarray:
    """Render a scene to a BGR uint8 image."""
    rng = rng if rng is not None else np.random.default_rng(0)
    h, w = scene.height, scene.width
    img = np.empty((h, w, 3), np.float32)
    img[:] = scene.bg_color

    if shadow is None:
        shadow = bool(degrade and rng.random() < 0.3)
    if shadow and scene.tablets:
        sh = np.zeros((h, w), np.float32)
        off = 4
        for t in scene.tablets:
            cv2.ellipse(sh, (int(t.cx + off), int(t.cy + off)), (int(t.a), int(t.b)),
                        t.angle, 0, 360, 1.0, -1, cv2.LINE_AA)
        sh = cv2.GaussianBlur(sh, (0, 0), 4)
        img *= (1.0 - 0.3 * sh)[..., None]

    for t in scene.tablets:
        r = int(math.ceil(t.a)) + 2
        x0, y0 = max(0, int(t.cx) - r), max(0, int(t.cy) - r)
        x1, y1 = min(w, int(t.cx) + r + 1), min(h, int(t.cy) + r + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        rho, u, v = _ellipse_rho(t, x0, y0, x1, y1)
        # ~1 px anti-aliased edge
        alpha = np.clip((1.0 - rho) * t.b, 0.0, 1.0)
        # radial shading: slightly darker towards the rim
        shade = 1.0 - 0.22 * np.clip(rho, 0, 1) ** 2
        col = np.array(t.color, np.float32)[None, None, :] * shade[..., None]
        if t.score_line:
            line = np.abs(u) < 1.2  # line across the minor axis direction
            col[line] *= 0.6
        crop = img[y0:y1, x0:x1]
        crop[:] = crop * (1 - alpha[..., None]) + col * alpha[..., None]

    if degrade:
        # mild linear illumination gradient
        g = rng.uniform(0.08, 0.15)
        ang = rng.uniform(0, 2 * math.pi)
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        ramp = ((xs / w - 0.5) * math.cos(ang) + (ys / h - 0.5) * math.sin(ang))
        img *= (1.0 + 2 * g * ramp)[..., None]
        sigma = rng.uniform(0.4, 1.1)
        img = cv2.GaussianBlur(img, (0, 0), sigma)
        img += rng.normal(0, rng.uniform(2.5, 7.0), img.shape).astype(np.float32)

    return np.clip(img, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Placement
# --------------------------------------------------------------------------- #
def _radius_along(t: Tablet, phi: float) -> float:
    """Ellipse radius in direction phi (radians)."""
    d = phi - math.radians(t.angle)
    return (t.a * t.b) / math.sqrt((t.b * math.cos(d)) ** 2 + (t.a * math.sin(d)) ** 2)


class _Occupancy:
    """Label image of placed tablets, used to reject unintended contacts."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.lab = np.zeros((h, w), np.int32)

    def fits(self, t: Tablet, gap: float, allowed: set[int], margin: int = 6) -> bool:
        r = int(math.ceil(t.a + gap)) + 1
        if (t.cx - t.a < margin or t.cy - t.a < margin or
                t.cx + t.a > self.w - margin or t.cy + t.a > self.h - margin):
            return False
        x0, y0 = max(0, int(t.cx) - r), max(0, int(t.cy) - r)
        x1, y1 = min(self.w, int(t.cx) + r + 1), min(self.h, int(t.cy) + r + 1)
        grown = Tablet(t.cx, t.cy, t.a + gap, t.b + gap, t.angle, t.color)
        rho, _, _ = _ellipse_rho(grown, x0, y0, x1, y1)
        hits = np.unique(self.lab[y0:y1, x0:x1][rho <= 1.0])
        hits = set(int(x) for x in hits) - {0}
        return hits <= allowed

    def add(self, t: Tablet, idx: int) -> None:
        cv2.ellipse(self.lab, (int(round(t.cx)), int(round(t.cy))),
                    (int(round(t.a)), int(round(t.b))), t.angle, 0, 360, idx, -1)


def random_scene(rng: np.random.Generator, n: int, background: str = "dark",
                 mode: str = "separated", width: int = CANVAS_W,
                 height: int = CANVAS_H) -> Scene:
    """Place up to n tablets of one type. The true count is len(scene.tablets)."""
    if background == "dark":
        base = rng.uniform(20, 70)
        tint = rng.uniform(-8, 8, 3)
        bg = tuple(int(np.clip(base + tt, 0, 255)) for tt in tint)
        palette = LIGHT_TABLET_COLORS
    else:
        base = rng.uniform(190, 245)
        tint = rng.uniform(-6, 6, 3)
        bg = tuple(int(np.clip(base + tt, 0, 255)) for tt in tint)
        palette = DARK_TABLET_COLORS
    color = palette[int(rng.integers(len(palette)))]

    aspect = 1.0 if rng.random() < 0.6 else float(rng.uniform(1.15, 1.6))
    # keep total tablet area <= ~22% of the canvas so placement succeeds
    r_max = math.sqrt(0.22 * width * height / (max(n, 1) * math.pi * aspect))
    r_hi = min(40.0, r_max)
    r_lo = min(15.0, r_hi)
    b0 = float(rng.uniform(r_lo, r_hi))           # minor semi-axis
    a0 = b0 * aspect
    score = rng.random() < 0.4

    occ = _Occupancy(width, height)
    tablets: list[Tablet] = []

    def make(cx, cy) -> Tablet:
        j = rng.uniform(0.96, 1.04)
        return Tablet(float(cx), float(cy), a0 * j, b0 * j, float(rng.uniform(0, 180)),
                      color, bool(score and rng.random() < 0.6))

    def place_free() -> Tablet | None:
        gap = max(4.0, 0.3 * b0)
        for _ in range(300):
            t = make(rng.uniform(a0, width - a0), rng.uniform(a0, height - a0))
            if occ.fits(t, gap, set()):
                return t
        return None

    def place_touching(prev: Tablet, prev_id: int) -> Tablet | None:
        gap = max(4.0, 0.3 * b0)
        for _ in range(60):
            phi = rng.uniform(0, 2 * math.pi)
            t = make(0, 0)
            overlap = rng.uniform(0.0, 0.15) * b0
            d = _radius_along(prev, phi) + _radius_along(t, phi + math.pi) - overlap
            t.cx, t.cy = prev.cx + d * math.cos(phi), prev.cy + d * math.sin(phi)
            if occ.fits(t, gap, {prev_id}):
                return t
        return None

    def commit(t: Tablet) -> int:
        tablets.append(t)
        occ.add(t, len(tablets))
        return len(tablets)

    n_free = n if mode == "separated" else (n // 2 if mode == "mixed" else 0)
    for _ in range(n_free):
        t = place_free()
        if t is not None:
            commit(t)
    misses = 0
    while len(tablets) < n and misses < 20:
        head = place_free()
        if head is None:
            misses += 1
            continue
        prev_id = commit(head)
        prev = head
        chain_len = int(rng.integers(2, 5))
        for _ in range(chain_len - 1):
            if len(tablets) >= n:
                break
            t = place_touching(prev, prev_id)
            if t is None:
                break
            prev_id, prev = commit(t), t

    return Scene(tablets, background, bg, width, height)


# --------------------------------------------------------------------------- #
# Controlled layouts for unit tests
# --------------------------------------------------------------------------- #
def _bg(background: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if background == "dark":
        return (35, 38, 40), (235, 235, 235)
    return (225, 228, 230), (40, 40, 170)


def grid_scene(n: int, background: str = "dark", r: float = 28.0,
               width: int = CANVAS_W, height: int = CANVAS_H) -> Scene:
    """n well-separated circles on a grid."""
    bg, col = _bg(background)
    cols = math.ceil(math.sqrt(n * width / height))
    rows = math.ceil(n / cols)
    dx, dy = width / (cols + 1), height / (rows + 1)
    tabs = [Tablet((i % cols + 1) * dx, (i // cols + 1) * dy, r, r, 0, col)
            for i in range(n)]
    return Scene(tabs, background, bg, width, height)


def pairs_scene(n_pairs: int, background: str = "dark", r: float = 28.0,
                overlap: float = 0.05) -> Scene:
    """n_pairs of circles touching edge to edge (overlap is a fraction of r)."""
    bg, col = _bg(background)
    cols = math.ceil(math.sqrt(n_pairs))
    rows = math.ceil(n_pairs / cols)
    dx, dy = CANVAS_W / (cols + 1), CANVAS_H / (rows + 1)
    d = 2 * r - overlap * r
    tabs = []
    for i in range(n_pairs):
        cx, cy = (i % cols + 1) * dx, (i // cols + 1) * dy
        ang = (i * 37) % 180
        ox, oy = d / 2 * math.cos(math.radians(ang)), d / 2 * math.sin(math.radians(ang))
        tabs += [Tablet(cx - ox, cy - oy, r, r, 0, col), Tablet(cx + ox, cy + oy, r, r, 0, col)]
    return Scene(tabs, background, bg)


# --------------------------------------------------------------------------- #
# Dataset writer
# --------------------------------------------------------------------------- #
LABEL_COLUMNS = ["filename", "true_count", "background", "condition", "split", "notes", "source"]


def split_for(index: int) -> str:
    """Deterministic ~1/3 tune, 2/3 test split."""
    return "tune" if index % 3 == 0 else "test"


def make_dataset(out_dir: str | Path, n: int = 200, seed: int = 42) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        background = "dark" if rng.random() < 0.5 else "light"
        mode = ["separated", "touching", "mixed"][int(rng.integers(3))]
        target = int(rng.integers(5, 61))
        scene = random_scene(rng, target, background, mode)
        img = render_scene(scene, rng, degrade=True)
        name = f"syn_{i + 1:03d}.png"
        cv2.imwrite(str(out / name), img)
        rows.append({"filename": name, "true_count": len(scene.tablets),
                     "background": background, "condition": mode, "split": split_for(i),
                     "notes": f"aspect={scene.tablets[0].a / scene.tablets[0].b:.2f}"
                              if scene.tablets else "", "source": "synthetic"})
    with open(out / "labels.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
        wr.writeheader()
        wr.writerows(rows)
    return out / "labels.csv"


def encode(img: np.ndarray, ext: str = ".png", quality: int = 92) -> bytes:
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if ext in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        raise RuntimeError("encode failed")
    return buf.tobytes()
