import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.main as main
from tools.synthetic import encode, grid_scene, render_scene


@pytest.fixture(scope="module")
def client():
    assert main.store is None, "S3 must be disabled in tests"
    return TestClient(main.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["opencv_version"].startswith("5")
    assert d["s3_enabled"] is False
    assert d["instance_type"] is None


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "TabCount" in r.text


def test_count_png(client, grid12_png):
    r = client.post("/api/count", files={"file": ("t.png", grid12_png, "image/png")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["count"] == 12
    assert d["baseline_count"] == 12
    assert d["opencv_version"].startswith("5")
    assert d["confidence"] == "high"
    assert {"decode", "segment", "watershed", "total"} <= set(d["timings_ms"])
    img = cv2.imdecode(np.frombuffer(base64.b64decode(d["annotated_jpeg_b64"]), np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    assert "debug_images_b64" not in d and "objects" not in d
    assert r.headers["X-Request-ID"] == d["request_id"]


def test_count_jpeg_with_overrides(client):
    data = encode(render_scene(grid_scene(8, "light"), np.random.default_rng(2)), ".jpg")
    r = client.post("/api/count?peak_ratio=0.6&cluster_correction=false&min_area_px=100",
                    files={"file": ("t.jpg", data, "image/jpeg")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["count"] == 8
    assert d["params"]["peak_ratio"] == 0.6 and d["params"]["cluster_correction"] is False


def test_bad_override_rejected(client, grid12_png):
    r = client.post("/api/count?peak_ratio=5", files={"file": ("t.png", grid12_png, "image/png")})
    assert r.status_code == 422
    assert set(r.json()) == {"error", "request_id"}


def test_txt_upload_415(client):
    r = client.post("/api/count", files={"file": ("a.txt", b"hello world", "text/plain")})
    assert r.status_code == 415
    assert set(r.json()) == {"error", "request_id"}


def test_too_large_413(client):
    big = b"\xff\xd8\xff" + b"\0" * (11 * 1024 * 1024)
    r = client.post("/api/count", files={"file": ("big.jpg", big, "image/jpeg")})
    assert r.status_code == 413
    assert "error" in r.json()


def test_corrupted_jpeg_400(client, grid12_png):
    good = encode(render_scene(grid_scene(4, "dark"), degrade=False), ".jpg")
    bad = good[:20] + b"\0" * 40  # valid JPEG magic, garbage body
    r = client.post("/api/count", files={"file": ("bad.jpg", bad, "image/jpeg")})
    assert r.status_code == 400
    assert set(r.json()) == {"error", "request_id"}


def test_debug_images(client, grid12_png):
    r = client.post("/api/count?debug=true", files={"file": ("t.png", grid12_png, "image/png")})
    assert r.status_code == 200
    d = r.json()
    assert {"mask", "distance", "seeds", "labels"} <= set(d["debug_images_b64"])
    assert len(d["objects"]) == 12


def test_results_404_without_s3(client):
    r = client.get("/api/results/00000000-0000-4000-8000-000000000000")
    assert r.status_code == 404


def test_s3_failure_never_breaks_response(client, grid12_png, monkeypatch):
    from app.storage import S3Store

    class Boom:
        calls = 0

        def put_object(self, **kw):
            Boom.calls += 1
            raise RuntimeError("S3 down")

    fake = S3Store("test-bucket")
    fake._client = Boom()
    monkeypatch.setattr(main, "store", fake)
    r = client.post("/api/count", files={"file": ("t.png", grid12_png, "image/png")})
    assert r.status_code == 200 and r.json()["count"] == 12
    assert Boom.calls == 1  # background task ran, failed, and was swallowed
