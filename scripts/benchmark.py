"""End-to-end latency/throughput benchmark against a TabCount URL.

    python scripts/benchmark.py --url http://ELASTIC_IP --images eval/data/real --n 100 --concurrency 4

Writes eval/results/benchmark.json and prints a markdown table.
Latency is measured on the client (includes network upload from where you run it).
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests

EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--images", default="eval/data/real")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default="eval/results/benchmark.json")
    a = ap.parse_args()

    url = a.url.rstrip("/")
    files = sorted(p for p in Path(a.images).iterdir() if p.suffix.lower() in EXTS)
    if not files:
        sys.exit(f"no images in {a.images}")
    payloads = [(p.name, p.read_bytes()) for p in files]
    health = requests.get(url + "/health", timeout=15).json()
    print(f"target {url}: {health}")

    def one(i):
        name, data = payloads[i % len(payloads)]
        ct = "image/png" if name.endswith(".png") else "image/jpeg"
        t0 = time.perf_counter()
        try:
            r = requests.post(url + "/api/count", files={"file": (name, data, ct)}, timeout=120)
            ms = (time.perf_counter() - t0) * 1000
            if r.status_code != 200:
                return ms, None, f"http {r.status_code}"
            return ms, r.json()["timings_ms"]["total"], None
        except Exception as exc:
            return (time.perf_counter() - t0) * 1000, None, type(exc).__name__

    one(0)  # warm-up, not counted
    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.concurrency) as ex:
        out = list(ex.map(one, range(a.n)))
    wall = time.perf_counter() - t0

    ok = [o for o in out if o[2] is None]
    lat = [o[0] for o in ok]
    srv = [o[1] for o in ok]
    q = lambda v, p: round(float(np.percentile(v, p)), 1) if v else None  # noqa: E731
    res = {
        "url": url, "health": health, "images_dir": a.images, "n_unique_images": len(payloads),
        "n_requests": a.n, "concurrency": a.concurrency, "errors": len(out) - len(ok),
        "error_kinds": sorted({o[2] for o in out if o[2]}),
        "e2e_latency_ms": {"p50": q(lat, 50), "p95": q(lat, 95), "p99": q(lat, 99), "mean": round(float(np.mean(lat)), 1) if lat else None},
        "server_pipeline_ms": {"p50": q(srv, 50), "p95": q(srv, 95)},
        "throughput_rps": round(len(ok) / wall, 2), "wall_s": round(wall, 2),
        "note": "End-to-end latency measured from the client machine, including upload over its network.",
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2))
    e, s = res["e2e_latency_ms"], res["server_pipeline_ms"]
    print("\n| Requests | Concurrency | Errors | E2E p50 | E2E p95 | E2E p99 | Server p50 | Throughput |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|")
    print(f"| {a.n} | {a.concurrency} | {res['errors']} | {e['p50']} ms | {e['p95']} ms | {e['p99']} ms | "
          f"{s['p50']} ms | {res['throughput_rps']} req/s |")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
