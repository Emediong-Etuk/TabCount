# Decisions log

Deviations from the original spec, and why. Newest last.

| # | Decision | Why |
|---|----------|-----|
| 1 | **Dev environment** is a Linux x86_64 cloud sandbox (Python 3.12.x). All tooling is plain Python so it also runs on Windows/macOS. | Build happened in a remote sandbox; the user's own OS is unknown, so every command is documented for both bash and PowerShell. |
| 2 | `opencv-python-headless==5.0.0.93` has a `manylinux2014_aarch64` wheel (`cp37-abi3`), so the Graviton (arm64) build uses the same pin. Verified with `pip download --platform manylinux2014_aarch64`. | Confirms the t4g plan is viable; no x86 fallback needed so far. |
| 3 | **Illumination flattening before Otsu** (`CountParams.flatten_background=True`). A quadratic surface is fitted to an 80×60 thumbnail with iterative outlier trimming, subtracted, and the image re-centred on the background level. | With few tablets and a lighting gradient, plain Otsu split the *background* into two classes (synthetic MAE 32.6 → 0.03 after the fix on a 40-image smoke test). Polarity is preserved, so the border-band polarity rule is unchanged. Costs ~5–15 ms. |
| 4 | Grayscale is computed from the blurred colour image (blur → gray) instead of gray → blur. | Both are linear, so the result is the same; this saves one blur because the watershed needs the blurred colour image anyway. |
| 5 | New warning `background_region_detected` when a single object covers >10% of the image; it forces confidence `low`. | Guards the cluster-correction from turning a mis-segmented background region into hundreds of "tablets". |
| 6 | Annotation text is ASCII: `x2` instead of `×2`, and `|` instead of `·` in the banner. The banner is drawn in a strip *above* the image. | OpenCV Hershey fonts only render ASCII. The strip keeps tablets near the top edge visible. |
| 7 | Imports: the repo root is put on `sys.path` by `pytest.ini` (`pythonpath = .`) for tests, and by a two-line bootstrap at the top of each `scripts/*.py` file, so `python scripts/x.py` works from the repo root. | One obvious way to run each script, on every OS, no packaging step. |
| 8 | Labels CSV has a 7th column `source` (`real`/`synthetic`) after the six specified columns. | Lets real and synthetic results stay clearly separated in every output. |
| 9 | Docker base image is `public.ecr.aws/docker/library/python:3.12-slim` (the official Docker image mirrored on AWS ECR Public) instead of `python:3.12-slim` from Docker Hub. | Docker Hub returned 429 (rate limit) during the build check; shared EC2 IPs hit the same limit. Same image, multi-arch. |
| 10 | No extra system packages in the image. | `opencv-python-headless` 5.0.0.93 imports cleanly on `python:3.12-slim`; verified by a build-time `import cv2` assertion. |
| 11 | uvicorn runs with `--no-access-log`. | Access logs contain client IP addresses; the spec forbids logging personal data. Our own JSON line per request is the only request log. |
| 12 | `deploy.py` runs Docker with `sudo` on the instance. | Avoids depending on the `docker` group membership taking effect in the first SSH session after boot. |
| 13 | EC2 root volume is 16 GB gp3, encrypted. | The 8 GB default is tight for the Docker build cache plus the image (~600 MB). |
| 14 | `GET /api/results/{id}` probes dated S3 prefixes (today back to 60 days), with an in-memory cache of recent IDs. | The least-privilege role has no `s3:ListBucket`, and keys are date-partitioned as specified. |
| 15 | Key pair type ED25519; written with LF line endings. | Supported by AWS and Windows OpenSSH; avoids CRLF issues on Windows. `provision.py` also runs the `icacls` commands on Windows. |
| 16 | Supported Python: 3.12–3.14 (Docker uses 3.12). 3.11 is **not** supported. | `numpy==2.5.4` (resolved by OpenCV 5.0.0.93) has no 3.11 wheels. Windows wheels verified for 3.12, 3.13, 3.14 (`opencv-python-headless` is an abi3 wheel). |
