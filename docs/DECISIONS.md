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
