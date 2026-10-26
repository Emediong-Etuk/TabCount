"""Deploy TabCount to the EC2 instance created by provision.py.

    python deploy/deploy.py --host ELASTIC_IP --key tabcount-key.pem

Steps: tar the repo (honouring .dockerignore) -> scp -> untar in ~/tabcount ->
docker build on the instance (native arm64) -> replace the container ->
poll /health -> run one synthetic image through /api/count -> confirm
arch == aarch64 and OpenCV 5.

Bucket and region default to deploy/state.json written by provision.py.
Uses the system ssh/scp (OpenSSH ships with Windows 10+).
"""
from __future__ import annotations

import argparse
import fnmatch
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

try:
    import numpy  # noqa: F401  (needed for the smoke test at the end)
except ModuleNotFoundError:
    raise SystemExit("Dependencies missing for this Python. Use the project venv (PowerShell):\n"
                     "  .venv\\Scripts\\python.exe -m pip install -r requirements-dev.txt\n"
                     "  .venv\\Scripts\\python.exe deploy/deploy.py --host IP --key tabcount-key.pem")

ALWAYS_EXCLUDE = ["deploy/state.json", "*.pem", ".env", ".venv", ".git", "**/__pycache__"]


def ignore_patterns() -> list[str]:
    pats = list(ALWAYS_EXCLUDE)
    di = ROOT / ".dockerignore"
    if di.exists():
        pats += [ln.strip().rstrip("/") for ln in di.read_text().splitlines()
                 if ln.strip() and not ln.startswith("#")]
    return pats


def excluded(rel: str, pats: list[str]) -> bool:
    parts = rel.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    for p in pats:
        p2 = p[3:] if p.startswith("**/") else p
        for pre in prefixes:
            if fnmatch.fnmatch(pre, p) or fnmatch.fnmatch(pre.split("/")[-1], p2):
                return True
    return False


def make_tarball(dest: Path) -> int:
    pats = ignore_patterns()
    n = 0
    with tarfile.open(dest, "w:gz") as tar:
        for path in sorted(ROOT.rglob("*")):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_dir() or excluded(rel, pats):
                continue
            tar.add(path, arcname=rel)
            n += 1
    return n


def run(cmd: list[str], check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    if not quiet:
        print("  $ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=check, text=True,
                          capture_output=quiet)


def http_json(url: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 30):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def multipart(name: str, filename: str, payload: bytes, ctype: str) -> tuple[bytes, str]:
    boundary = "----tabcount" + str(int(time.time() * 1000))
    body = io.BytesIO()
    body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
               f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
    body.write(payload)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=None, help="Elastic IP (default: from deploy/state.json)")
    ap.add_argument("--key", default=None, help="path to tabcount-key.pem")
    ap.add_argument("--user", default="ec2-user")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--region", default=None)
    ap.add_argument("--no-s3", action="store_true", help="run without S3 persistence")
    a = ap.parse_args()

    state = json.loads((HERE / "state.json").read_text()) if (HERE / "state.json").exists() else {}
    host = a.host or state.get("elastic_ip")
    key = a.key or state.get("key_path") or str(ROOT / "tabcount-key.pem")
    region = a.region or state.get("region") or "eu-west-1"
    bucket = None if a.no_s3 else (a.bucket or state.get("bucket"))
    if not host:
        sys.exit("--host is required (or run provision.py first)")
    if not Path(key).exists():
        sys.exit(f"key not found: {key}")

    ssh_opts = ["-i", key, "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15",
                "-o", "ServerAliveInterval=30"]
    target = f"{a.user}@{host}"

    print(f"[1/6] Packaging repo for {host}")
    tmp = Path(tempfile.mkdtemp()) / "tabcount.tar.gz"
    n = make_tarball(tmp)
    print(f"  {n} files, {tmp.stat().st_size / 1024:.0f} KB")

    print("[2/6] Waiting for SSH and Docker (first boot installs Docker; can take ~2 min)")
    for i in range(40):
        r = run(["ssh", *ssh_opts, target, "sudo docker info >/dev/null 2>&1 && echo READY"], check=False, quiet=True)
        if "READY" in (r.stdout or ""):
            print("  instance ready")
            break
        time.sleep(6)
    else:
        sys.exit("instance not ready: check `ssh ... sudo cat /var/log/cloud-init-output.log`")

    print("[3/6] Uploading")
    run(["scp", *ssh_opts, str(tmp), f"{target}:tabcount.tar.gz"])

    env = [f"-e AWS_REGION={region}"]
    if bucket:
        env.append(f"-e TABCOUNT_S3_BUCKET={bucket}")
    docker_run = (
        "sudo docker run -d --name tabcount --restart unless-stopped -p 80:8000 "
        + " ".join(env) + " "
        f"--log-driver awslogs --log-opt awslogs-region={region} "
        "--log-opt awslogs-group=/tabcount/app --log-opt awslogs-create-group=true "
        "tabcount:latest"
    )
    remote = " && ".join([
        "rm -rf ~/tabcount && mkdir -p ~/tabcount",
        "tar xzf ~/tabcount.tar.gz -C ~/tabcount",
        "cd ~/tabcount",
        "sudo docker build -t tabcount:latest .",
        "(sudo docker rm -f tabcount >/dev/null 2>&1 || true)",
        docker_run,
        "sudo docker image prune -f >/dev/null",
    ])
    print("[4/6] Building the image on the instance and replacing the container")
    run(["ssh", *ssh_opts, target, remote])

    print(f"[5/6] Polling http://{host}/health (timeout 120 s)")
    t0, health = time.time(), None
    while time.time() - t0 < 120:
        try:
            status, health = http_json(f"http://{host}/health", timeout=5)
            if status == 200:
                break
        except Exception:
            pass
        time.sleep(3)
    if not health:
        sys.exit("health check failed; inspect with: ssh ... sudo docker logs tabcount")
    print("  " + json.dumps(health))

    print("[6/6] Smoke test: one synthetic image through /api/count")
    import numpy as np
    from tools.synthetic import encode, pairs_scene, render_scene
    img = encode(render_scene(pairs_scene(6, "dark"), np.random.default_rng(0)), ".jpg")
    body, ctype = multipart("file", "smoke.jpg", img, "image/jpeg")
    status, d = http_json(f"http://{host}/api/count", data=body, headers={"Content-Type": ctype}, timeout=60)
    print(f"  status {status}: count={d['count']} (true 12) baseline={d['baseline_count']} "
          f"confidence={d['confidence']} server={d['timings_ms']['total']} ms request_id={d['request_id']}")

    ok_arch = health.get("arch") == "aarch64"
    ok_cv = str(health.get("opencv_version", "")).startswith("5")
    print("\nChecks")
    print(f"  arch == aarch64     : {'OK' if ok_arch else 'NO (' + str(health.get('arch')) + ')'}")
    print(f"  OpenCV 5.x          : {'OK' if ok_cv else 'NO'} ({health.get('opencv_version')})")
    print(f"  instance type       : {health.get('instance_type')}")
    print(f"  S3 enabled          : {health.get('s3_enabled')}")
    print(f"  smoke count correct : {'OK' if d['count'] == 12 else 'NO'}")
    print(f"\nLive URL: http://{host}/")
    if not ok_cv:
        sys.exit(1)


if __name__ == "__main__":
    main()
