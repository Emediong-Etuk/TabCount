"""TabCount FastAPI app.

Run: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --no-access-log
(--no-access-log keeps client IPs out of the logs.)
"""
from __future__ import annotations

import base64
import json
import logging
import platform
import sys
import threading
import time
import urllib.request
import uuid
from dataclasses import replace
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.baseline import baseline_from_preprocessed
from app.config import MIN_AREA_RANGE, PEAK_RATIO_RANGE, Settings
from app.counter import (ARCH, OPENCV_VERSION, CountParams, InvalidImageError,
                         count_preprocessed, preprocess)
from app.storage import S3Store

STATIC = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger("tabcount")

settings = Settings.from_env()
store = S3Store(settings.s3_bucket, settings.aws_region) if settings.s3_enabled else None

app = FastAPI(title="TabCount", version="1.0.0",
              description="Counts tablets in a photo with an OpenCV 5 pipeline.")


# --------------------------------------------------------------------------- #
# Errors: always {"error": "...", "request_id": "..."}
# --------------------------------------------------------------------------- #
class APIError(Exception):
    def __init__(self, status: int, message: str, request_id: str):
        self.status, self.message, self.request_id = status, message, request_id


def _err(status: int, message: str, request_id: str | None = None) -> JSONResponse:
    rid = request_id or str(uuid.uuid4())
    return JSONResponse({"error": message, "request_id": rid}, status_code=status,
                        headers={"X-Request-ID": rid})


@app.exception_handler(APIError)
async def _api_error(_: Request, exc: APIError):
    return _err(exc.status, exc.message, exc.request_id)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    parts = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", []) if x not in ("query", "body"))
        parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
    return _err(422, "invalid request: " + "; ".join(parts))


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException):
    return _err(exc.status_code, str(exc.detail))


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    log.error(json.dumps({"event": "error", "error": type(exc).__name__}))
    return _err(500, "internal error")


# --------------------------------------------------------------------------- #
# EC2 instance type (IMDSv2), read once and cached; None off EC2.
# --------------------------------------------------------------------------- #
_instance_type: dict = {}
_imds_lock = threading.Lock()


def instance_type() -> str | None:
    with _imds_lock:
        if "v" in _instance_type:
            return _instance_type["v"]
        value = None
        if not settings.disable_imds:
            try:
                req = urllib.request.Request(
                    "http://169.254.169.254/latest/api/token", method="PUT",
                    headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
                token = urllib.request.urlopen(req, timeout=0.5).read().decode()
                req = urllib.request.Request(
                    "http://169.254.169.254/latest/meta-data/instance-type",
                    headers={"X-aws-ec2-metadata-token": token})
                value = urllib.request.urlopen(req, timeout=0.5).read().decode().strip() or None
            except Exception:
                value = None
        _instance_type["v"] = value
        return value


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "opencv_version": OPENCV_VERSION,
        "arch": ARCH,
        "python_version": platform.python_version(),
        "s3_enabled": settings.s3_enabled,
        "instance_type": instance_type(),
    }


def sniff_type(data: bytes) -> str | None:
    """Detect JPEG/PNG/WebP from magic bytes (the client's Content-Type is not trusted)."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


@app.post("/api/count")
def api_count(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    peak_ratio: float | None = Query(None, ge=PEAK_RATIO_RANGE[0], le=PEAK_RATIO_RANGE[1]),
    cluster_correction: bool | None = Query(None),
    min_area_px: int | None = Query(None, ge=MIN_AREA_RANGE[0], le=MIN_AREA_RANGE[1]),
    debug: bool = Query(False),
):
    request_id = str(uuid.uuid4())
    t0 = time.perf_counter()

    limit = settings.max_upload_bytes
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise APIError(413, f"file too large (max {limit // (1024 * 1024)} MB)", request_id)
    kind = sniff_type(data)
    if kind is None:
        raise APIError(415, "unsupported file type: upload a JPEG, PNG or WebP image", request_id)

    params = CountParams()
    overrides = {k: v for k, v in {"peak_ratio": peak_ratio, "cluster_correction": cluster_correction,
                                   "min_area_px": min_area_px}.items() if v is not None}
    if overrides:
        params = replace(params, **overrides)

    try:
        t_pre = time.perf_counter()
        pre = preprocess(data, params)
    except InvalidImageError:
        raise APIError(400, "could not decode the image", request_id)
    result = count_preprocessed(pre, params, debug=debug,
                                t_start=t_pre + pre.timings_ms["decode"] / 1000.0)
    baseline = baseline_from_preprocessed(pre, params)
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    body = {
        "request_id": request_id,
        "count": result.count,
        "segments": result.segments,
        "clusters_flagged": result.clusters_flagged,
        "debris_removed": result.debris_removed,
        "confidence": result.confidence,
        "warnings": result.warnings,
        "baseline_count": baseline,
        "polarity": result.polarity,
        "otsu_threshold": result.otsu_threshold,
        "timings_ms": result.timings_ms,
        "latency_ms": latency_ms,
        "image": result.image,
        "params": result.params,
        "opencv_version": result.opencv_version,
        "arch": result.arch,
        "annotated_jpeg_b64": _b64(result.annotated_jpeg),
    }
    if debug:
        body["objects"] = result.objects
        body["debug_images_b64"] = {k: _b64(v) for k, v in result.debug_images.items()}

    log.info(json.dumps({
        "event": "count", "request_id": request_id, "count": result.count,
        "baseline_count": baseline, "confidence": result.confidence, "latency_ms": latency_ms,
        "stage_ms": result.timings_ms, "proc_w": result.image["proc_w"],
        "proc_h": result.image["proc_h"], "arch": result.arch, "opencv": result.opencv_version,
    }))

    if store is not None:
        stored = result.to_dict()
        stored.update({"request_id": request_id, "baseline_count": baseline, "latency_ms": latency_ms})
        background_tasks.add_task(store.save_request, request_id, data, kind,
                                  result.annotated_jpeg, stored)

    return JSONResponse(body, headers={"X-Request-ID": request_id})


@app.get("/api/results/{request_id}")
def api_result(request_id: str):
    if store is None:
        raise APIError(404, "result storage is not enabled", request_id)
    found = store.get_result(request_id)
    if found is None:
        raise APIError(404, "result not found", request_id)
    return found
