"""TabCount OpenCV 5 counting pipeline.

preprocess() -> segment() -> watershed -> postprocess() -> annotate()

Classic computer vision only (no deep learning). Uses only OpenCV core/imgproc.
"""
from __future__ import annotations

import math
import platform
import time
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

# --------------------------------------------------------------------------- #
# OpenCV 5 guard: this project must run on OpenCV 5.x
# --------------------------------------------------------------------------- #
OPENCV_VERSION: str = cv2.__version__
if not OPENCV_VERSION.startswith("5"):
    raise RuntimeError(
        f"TabCount requires OpenCV 5.x, found cv2 {OPENCV_VERSION}. "
        "Install exactly one OpenCV package: pip install opencv-python-headless==5.0.0.93"
    )

ARCH: str = platform.machine()

GREEN = (60, 200, 60)
ORANGE = (0, 140, 255)
RED = (40, 40, 230)


class InvalidImageError(ValueError):
    """Raised when the uploaded bytes cannot be decoded as an image."""


@dataclass(frozen=True)
class CountParams:
    max_side: int = 1200          # resize so the longest side <= this (never upscale)
    blur_ksize: int = 5           # Gaussian blur kernel (odd)
    close_iterations: int = 1     # bridges thin score lines/imprints inside tablets
    open_iterations: int = 2      # removes specks/dust
    peak_ratio: float = 0.5       # watershed seed threshold, relative to EACH blob's own max distance
    min_area_px: int = 60         # absolute area floor (at max_side scale)
    debris_ratio: float = 0.25    # objects < debris_ratio * median area are dropped as crumbs
    cluster_ratio: float = 1.8    # objects > cluster_ratio * median area are flagged as clusters
    cluster_correction: bool = True  # flagged objects count as round(area / median)
    flatten_background: bool = True  # remove smooth illumination gradients before Otsu (see DECISIONS.md)


@dataclass
class Preprocessed:
    """Output of preprocess(); shared by the main pipeline and the baseline."""
    bgr: np.ndarray               # resized colour image
    blurred_bgr: np.ndarray
    mask: np.ndarray              # uint8, tablets = 255, holes filled
    orig_w: int
    orig_h: int
    scale: float
    otsu_threshold: float
    polarity: str
    fg_fraction: float
    warnings: list[str]
    timings_ms: dict[str, float]


@dataclass
class CountResult:
    count: int
    segments: int
    clusters_flagged: int
    debris_removed: int
    confidence: str
    warnings: list[str]
    polarity: str
    otsu_threshold: float
    objects: list[dict]
    image: dict
    params: dict
    timings_ms: dict[str, float]
    opencv_version: str = OPENCV_VERSION
    arch: str = ARCH
    annotated_jpeg: bytes = b""
    debug_images: dict[str, bytes] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-serialisable dict (image bytes excluded)."""
        d = asdict(self)
        d.pop("annotated_jpeg", None)
        d.pop("debug_images", None)
        return d


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000.0, 2)


def _jpeg(img: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def flatten_illumination(gray: np.ndarray) -> np.ndarray:
    """Remove a smooth lighting gradient from the background.

    Fits a quadratic surface to a 80x60 thumbnail with iterative outlier
    trimming (tablets are outliers, background is the majority), then
    subtracts it and re-centres on the background level (polarity is kept). Without this, Otsu on a photo with
    few tablets and uneven lighting splits the *background* into two classes.
    """
    h, w = gray.shape
    sw, sh = 80, 60
    small = cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    xx = (xx / (sw - 1)) * 2 - 1
    yy = (yy / (sh - 1)) * 2 - 1
    X = np.stack([np.ones_like(xx), xx, yy, xx * xx, xx * yy, yy * yy], -1).reshape(-1, 6)
    keep = np.ones(small.size, bool)
    coef = np.zeros(6, np.float32)
    for _ in range(5):
        coef, *_ = np.linalg.lstsq(X[keep], small[keep], rcond=None)
        res = small - X @ coef
        s = 1.4826 * float(np.median(np.abs(res[keep]))) + 1.0
        new_keep = np.abs(res) < 2.5 * s
        if new_keep.sum() < 0.3 * small.size:
            break
        keep = new_keep
    surf = (X @ coef).reshape(sh, sw).astype(np.float32)
    bg = cv2.resize(surf, (w, h), interpolation=cv2.INTER_LINEAR)
    level = float(np.median(small[keep]))
    out = gray.astype(np.float32) - bg + level
    return np.clip(out, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# 1-8. Decode, resize, grayscale, blur, Otsu, polarity, morphology, fill holes
# --------------------------------------------------------------------------- #
def preprocess(data: bytes, params: CountParams = CountParams()) -> Preprocessed:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    if not data:
        raise InvalidImageError("empty upload")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        raise InvalidImageError("could not decode image")
    timings["decode"] = _ms(t0)

    t1 = time.perf_counter()
    orig_h, orig_w = img.shape[:2]
    scale = min(1.0, params.max_side / float(max(orig_w, orig_h)))
    if scale < 1.0:
        img = cv2.resize(img, (max(1, round(orig_w * scale)), max(1, round(orig_h * scale))),
                         interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]

    k = params.blur_ksize | 1
    blurred_bgr = cv2.GaussianBlur(img, (k, k), 0)
    gray = cv2.cvtColor(blurred_bgr, cv2.COLOR_BGR2GRAY)
    if params.flatten_background:
        gray = flatten_illumination(gray)

    otsu_t, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Polarity: the border band should be background. If it is mostly "on",
    # the background is the bright class, so invert (tablets must be 255).
    band = max(1, int(round(0.03 * min(h, w))))
    border = np.concatenate([binary[:band].ravel(), binary[-band:].ravel(),
                             binary[band:-band, :band].ravel(), binary[band:-band, -band:].ravel()])
    if np.count_nonzero(border) / max(1, border.size) > 0.5:
        binary = cv2.bitwise_not(binary)
        polarity = "dark_on_light"
    else:
        polarity = "light_on_dark"

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    if params.close_iterations > 0:
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=params.close_iterations)
    if params.open_iterations > 0:
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=params.open_iterations)

    # Fill holes left by imprints/highlights: redraw external contours filled.
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(binary)
    if contours:
        cv2.drawContours(mask, contours, -1, 255, cv2.FILLED)

    fg = np.count_nonzero(mask) / float(mask.size)
    warnings: list[str] = []
    if fg < 0.001:
        warnings.append("no_tablets_found")
    elif fg > 0.7:
        warnings.append("low_contrast_or_background_not_detected")
    timings["preprocess"] = _ms(t1)

    return Preprocessed(img, blurred_bgr, mask, orig_w, orig_h, scale, float(otsu_t),
                        polarity, fg, warnings, timings)


# --------------------------------------------------------------------------- #
# 9-10. Distance transform + per-blob seeds
# --------------------------------------------------------------------------- #
def segment(mask: np.ndarray, peak_ratio: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (distance map float32, seeds uint8 0/255).

    Seeds are normalised per blob: a pixel is a seed if its distance is at
    least peak_ratio * (max distance inside its own blob). This keeps seeds
    sensible when blobs of very different sizes appear in one image.
    """
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    n_blobs, blobs = cv2.connectedComponents(mask, connectivity=8)
    blob_max = np.zeros(n_blobs, np.float32)
    fg = blobs > 0
    np.maximum.at(blob_max, blobs[fg], dist[fg])
    thresh = peak_ratio * blob_max
    seeds = np.zeros(mask.shape, np.uint8)
    seeds[fg & (dist >= thresh[blobs]) & (dist > 0)] = 255
    return dist, seeds


def run_watershed(blurred_bgr: np.ndarray, mask: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """Marker-based watershed. Returns int32 labels: >=2 objects, 1 bg, -1 boundaries."""
    _, markers = cv2.connectedComponents(seeds, connectivity=8)
    markers = markers.astype(np.int32) + 1
    kernel = np.ones((3, 3), np.uint8)
    sure_bg = cv2.dilate(mask, kernel, iterations=2)
    unknown = (sure_bg > 0) & (seeds == 0)
    markers[unknown] = 0
    return cv2.watershed(blurred_bgr, markers)


# --------------------------------------------------------------------------- #
# 12-14. Object statistics, filtering, clusters, confidence
# --------------------------------------------------------------------------- #
def object_stats(labels: np.ndarray, mask: np.ndarray) -> list[dict]:
    """Area/centroid/bbox per watershed label in one vectorised pass."""
    valid = (labels >= 2) & (mask > 0)
    ys, xs = np.nonzero(valid)
    if ys.size == 0:
        return []
    ids = labels[ys, xs]
    n = int(ids.max()) + 1
    area = np.bincount(ids, minlength=n)
    sx = np.bincount(ids, weights=xs, minlength=n)
    sy = np.bincount(ids, weights=ys, minlength=n)
    big = np.iinfo(np.int64).max
    xmin = np.full(n, big, np.int64); ymin = np.full(n, big, np.int64)
    xmax = np.full(n, -1, np.int64); ymax = np.full(n, -1, np.int64)
    np.minimum.at(xmin, ids, xs); np.minimum.at(ymin, ids, ys)
    np.maximum.at(xmax, ids, xs); np.maximum.at(ymax, ids, ys)
    objs = []
    for lid in np.nonzero(area)[0]:
        a = int(area[lid])
        objs.append({
            "label": int(lid),
            "area": a,
            "centroid": [round(float(sx[lid]) / a, 1), round(float(sy[lid]) / a, 1)],
            "bbox": [int(xmin[lid]), int(ymin[lid]),
                     int(xmax[lid] - xmin[lid] + 1), int(ymax[lid] - ymin[lid] + 1)],
        })
    return objs


def postprocess(objs: list[dict], params: CountParams, warnings: list[str],
                image_area: int | None = None) -> dict:
    """Filter debris, flag clusters, compute count and confidence.

    May append to `warnings` (e.g. when one object is implausibly large,
    which usually means part of the background was segmented as foreground).
    """
    objs = [o for o in objs if o["area"] >= params.min_area_px]
    if image_area and any(o["area"] > 0.10 * image_area for o in objs):
        if "background_region_detected" not in warnings:
            warnings.append("background_region_detected")
    debris = 0
    median = float(np.median([o["area"] for o in objs])) if objs else 0.0
    if len(objs) >= 3:
        keep = [o for o in objs if o["area"] >= params.debris_ratio * median]
        debris = len(objs) - len(keep)
        objs = keep
        for o in objs:
            flagged = o["area"] > params.cluster_ratio * median
            o["flagged"] = bool(flagged)
            o["est_units"] = max(1, int(round(o["area"] / median))) if flagged else 1
    else:
        for o in objs:
            o["flagged"] = False
            o["est_units"] = 1

    # Number objects in reading order (rows of roughly one tablet height).
    if objs:
        row_h = max(1.0, 2.0 * math.sqrt(median / math.pi)) if median > 0 else 1.0
        objs.sort(key=lambda o: (int(o["centroid"][1] // row_h), o["centroid"][0]))
    for i, o in enumerate(objs, start=1):
        o["id"] = i

    segments = len(objs)
    flagged = sum(1 for o in objs if o["flagged"])
    count = sum(o["est_units"] for o in objs) if params.cluster_correction else segments

    if segments >= 3 and flagged == 0 and not warnings:
        confidence = "high"
    elif segments >= 3 and not warnings and flagged <= 0.10 * segments:
        confidence = "medium"
    else:
        confidence = "low"
    return {"objects": objs, "count": int(count), "segments": segments,
            "clusters_flagged": flagged, "debris_removed": debris,
            "confidence": confidence, "median_area": median}


# --------------------------------------------------------------------------- #
# 15. Annotation
# --------------------------------------------------------------------------- #
def _object_contour(labels: np.ndarray, mask: np.ndarray, o: dict):
    x, y, w, h = o["bbox"]
    crop = ((labels[y:y + h, x:x + w] == o["label"]) & (mask[y:y + h, x:x + w] > 0)).astype(np.uint8)
    cs, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE, offset=(x, y))
    return max(cs, key=cv2.contourArea) if cs else None


def annotate(bgr: np.ndarray, labels: np.ndarray, mask: np.ndarray, post: dict,
             elapsed_ms: float) -> np.ndarray:
    out = bgr.copy()
    h, w = out.shape[:2]
    median = post["median_area"]
    r = math.sqrt(median / math.pi) if median > 0 else 20.0
    fs = float(np.clip(r / 40.0, 0.35, 1.1))
    th = max(1, int(round(fs * 2)))
    line_w = max(2, int(round(min(h, w) / 400)))

    for o in post["objects"]:
        c = _object_contour(labels, mask, o)
        color = (RED if o["est_units"] >= 3 else ORANGE) if o["flagged"] else GREEN
        if c is not None:
            cv2.drawContours(out, [c], -1, color, line_w, cv2.LINE_AA)
    for o in post["objects"]:
        text = str(o["id"]) + (f" x{o['est_units']}" if o["flagged"] else "")
        (tw, tht), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
        cx, cy = int(o["centroid"][0]), int(o["centroid"][1])
        x0, y0 = cx - tw // 2 - 2, cy - tht // 2 - 2
        box_col = ORANGE if o["flagged"] else (30, 30, 30)
        cv2.rectangle(out, (x0, y0), (x0 + tw + 4, y0 + tht + base + 2), box_col, cv2.FILLED)
        cv2.putText(out, text, (x0 + 2, y0 + tht + 1), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    (255, 255, 255), th, cv2.LINE_AA)

    # Banner strip above the image so it never hides tablets.
    bfs = float(np.clip(w / 1400.0, 0.5, 1.0))
    bth = max(1, int(round(bfs * 2)))
    banner = (f"Count: {post['count']} | conf: {post['confidence']} | {elapsed_ms:.0f} ms"
              f" | OpenCV {OPENCV_VERSION} | {ARCH}")
    (_, bh), bb = cv2.getTextSize(banner, cv2.FONT_HERSHEY_SIMPLEX, bfs, bth)
    pad = int(bh * 0.6) + 4
    out = cv2.copyMakeBorder(out, bh + bb + 2 * pad, 0, 0, 0, cv2.BORDER_CONSTANT, value=(25, 25, 25))
    cv2.putText(out, banner, (pad, pad + bh), cv2.FONT_HERSHEY_SIMPLEX, bfs,
                (255, 255, 255), bth, cv2.LINE_AA)
    return out


def _debug_images(pre: Preprocessed, dist: np.ndarray, seeds: np.ndarray,
                  labels: np.ndarray, annotated: np.ndarray) -> dict[str, bytes]:
    dn = cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    dist_col = cv2.applyColorMap(dn, cv2.COLORMAP_JET)
    dist_col[pre.mask == 0] = 0
    rng = np.random.default_rng(7)
    n = int(labels.max()) + 2
    lut = rng.integers(60, 255, (n, 3), dtype=np.uint8)
    lab_img = lut[np.clip(labels, 0, None)]
    lab_img[labels <= 1] = 0
    lab_img[labels == -1] = 255
    return {"mask": _jpeg(pre.mask), "distance": _jpeg(dist_col), "seeds": _jpeg(seeds),
            "labels": _jpeg(lab_img), "annotated": _jpeg(annotated)}


# --------------------------------------------------------------------------- #
# Top level
# --------------------------------------------------------------------------- #
def count_preprocessed(pre: Preprocessed, params: CountParams = CountParams(),
                       debug: bool = False, t_start: float | None = None) -> CountResult:
    t_start = t_start if t_start is not None else time.perf_counter()
    timings = dict(pre.timings_ms)
    warnings = list(pre.warnings)

    t = time.perf_counter()
    dist, seeds = segment(pre.mask, params.peak_ratio)
    timings["segment"] = _ms(t)

    t = time.perf_counter()
    labels = run_watershed(pre.blurred_bgr, pre.mask, seeds)
    timings["watershed"] = _ms(t)

    t = time.perf_counter()
    post = postprocess(object_stats(labels, pre.mask), params, warnings, pre.mask.size)
    timings["postprocess"] = _ms(t)

    t = time.perf_counter()
    elapsed = (t - t_start) * 1000.0 + timings.get("decode", 0.0)
    annotated = annotate(pre.bgr, labels, pre.mask, post, elapsed)
    annotated_jpeg = _jpeg(annotated)
    timings["annotate"] = _ms(t)

    debug_imgs = _debug_images(pre, dist, seeds, labels, annotated) if debug else {}
    timings["total"] = round(sum(v for k, v in timings.items() if k != "total"), 2)

    h, w = pre.bgr.shape[:2]
    objects = [{"id": o["id"], "area": o["area"], "centroid": o["centroid"], "bbox": o["bbox"],
                "flagged": o["flagged"], "est_units": o["est_units"]} for o in post["objects"]]
    return CountResult(
        count=post["count"], segments=post["segments"], clusters_flagged=post["clusters_flagged"],
        debris_removed=post["debris_removed"], confidence=post["confidence"], warnings=warnings,
        polarity=pre.polarity, otsu_threshold=pre.otsu_threshold, objects=objects,
        image={"orig_w": pre.orig_w, "orig_h": pre.orig_h, "proc_w": w, "proc_h": h,
               "scale": round(pre.scale, 4)},
        params=asdict(params), timings_ms=timings, annotated_jpeg=annotated_jpeg,
        debug_images=debug_imgs,
    )


def count_tablets(image_bytes: bytes, params: CountParams = CountParams(),
                  debug: bool = False) -> CountResult:
    """Count tablets in an encoded image (JPEG/PNG/WebP bytes)."""
    t0 = time.perf_counter()
    pre = preprocess(image_bytes, params)
    # decode time is already in pre.timings_ms; t_start excludes it to avoid double counting
    return count_preprocessed(pre, params, debug, t_start=t0 + pre.timings_ms["decode"] / 1000.0)
