<!-- Generated into docs/DEVPOST.md by scripts/fill_report.py. Edit this template, not DEVPOST.md. -->
# Devpost submission text (copy-paste)

**Project name:** TabCount
**Tagline:** Count loose tablets from one phone photo: OpenCV 5 on AWS Graviton.

**Links**
- Live demo: {{LIVE_URL}}
- Code: https://github.com/emediong-etuk/tabcount
- Technical report: https://github.com/emediong-etuk/tabcount/blob/main/docs/REPORT.md
- Video: {{VIDEO_URL}}

## Inspiration
In Nigerian community pharmacies and patent medicine stores, tablets are dispensed loose and counted by
hand, usually in fives with a spatula, at the counter and again at stock-take. It is slow when the shop is
busy, and every miscount costs money or short-changes a patient. Counting machines are costly; a camera
phone is already in every assistant's pocket. We wanted that phone to do the counting and show its work.

## What it does
You spread tablets in a single layer on a plain, contrasting tray, take a photo in the TabCount web page,
and get:
- **the count**,
- **a confidence level** (high / medium / low),
- **an annotated image** with every tablet outlined and numbered, with possible clusters in orange,
- plain-language warnings such as "2 spots may be touching or stacked tablets. Check the orange outlines."

It also shows the naive contour count, so you can see what the watershed step adds.
No install, no account, no personal data.

## How we built it
- **OpenCV 5 pipeline** (classic CV, CPU only): decode and resize → blur → illumination flattening →
  Otsu threshold with automatic polarity detection → morphology and hole filling → distance transform →
  **per-blob seed normalisation** → marker-based **watershed** → median-area debris filtering and cluster
  correction → annotation. A guard refuses to run on anything but OpenCV 5.x.
- **FastAPI** backend and one vanilla-JS mobile page that downscales photos before upload.
- **AWS:** Docker on **EC2 t4g.small (Graviton, arm64)** with an Elastic IP; IMDSv2 required (hop limit 2)
  so the container uses a **least-privilege IAM role**; private **S3** (SSE-S3, 60-day lifecycle) for
  inputs, annotated images and results; **CloudWatch Logs** with one JSON line per request.
- **Evaluation:** {{REAL_N}} real phone photos hand-counted twice, with a tune/test split; plus 200
  synthetic images reported separately. We also ran a live benchmark and a check that the deployed
  endpoint returns exactly the same counts as the local evaluation.

## Challenges we ran into
- **Touching tablets.** Plain contour counting merges every touching group. A global distance threshold
  fails when blob sizes vary, so we normalise seeds **per blob** by each blob's own maximum distance.
- **Otsu splitting the background.** With few tablets and uneven light, Otsu divided the background
  itself. A robust quadratic illumination fit before thresholding fixed it.
- **Container credentials.** boto3 inside Docker cannot reach IMDSv2 with the default hop limit of 1;
  it must be 2.
- Staying honest: synthetic accuracy is far higher than real-photo accuracy, so we report them separately.

## Accomplishments that we're proud of
- On real photos (test split, n={{REAL_N_TEST}}): exact count on **{{REAL_EXACT}}** of photos, within ±1 on
  **{{REAL_WITHIN1}}**, MAE **{{REAL_MAE}}**, against **{{REAL_BASE_EXACT}}** exact (MAE {{REAL_BASE_MAE}}) for
  the naive contour baseline on identical preprocessing.
- Deployed consistency: **{{CONSIST_MATCHES}}/{{CONSIST_N}}** test images returned identical counts from the
  live arm64 endpoint and the local evaluation.
- Live endpoint: end-to-end p50 **{{BENCH_P50}} ms** (server pipeline p50 {{BENCH_SERVER_P50}} ms) on a t4g.small.
- A failure gallery that shows exactly where it breaks: stacking, glare, white on white.

## What we learned
- Classic OpenCV still solves a real problem well when the capture conditions are controlled. Most of
  the accuracy comes from the capture instructions and from honest confidence signals.
- Evaluation discipline (tune/test split, baseline, ablation, failure cases) changes which features are worth building.
- arm64 on AWS was easy for a CPU-only OpenCV 5 workload: the published wheel installs natively.

## What's next for TabCount
- Guided capture: live overlay that checks contrast, glare and single-layer spread before the shot.
- On-device processing (OpenCV.js) for offline pharmacies.
- Integration with pharmacy stock systems, with the annotated image as an audit record.
- Counting two tablet types in one photo.

## Built with
opencv, opencv-5, python, numpy, fastapi, uvicorn, docker, aws, amazon-ec2, aws-graviton, amazon-s3,
amazon-cloudwatch, aws-iam, html, javascript

## Team
Emediong Etuk Gregory ("Greg"): backend engineer (PHP/Laravel, Next.js/TypeScript), B.Eng. Computer
Engineering, University of Uyo, Nigeria. Solo entry. Not entering any featured path.
