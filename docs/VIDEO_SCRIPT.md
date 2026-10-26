# Video script (target 4:30, hard limit 5:00)

Record in landscape at 1080p. Use your phone (or a screen-mirroring app such as scrcpy or Windows
Phone Link) for the demo and your laptop for the slides and figures. Speak slowly; the narration below
runs about 4:15 at a calm pace. Fill in the `{{…}}` numbers from `docs/DEVPOST.md` after `fill_report.py` has run.

**Before recording:** have three trays ready: (A) about 15 separated tablets on a dark cloth, (B) about 25
tablets pushed into touching groups, (C) the same with two tablets partly stacked. Open the live URL on the
phone. On the laptop, open `docs/architecture.png`, `docs/figures/pipeline_stages.png`,
`eval/results/real/summary.md`, `docs/figures/real_scatter_pred_vs_true.png` and
`docs/figures/real_failures_contact_sheet.jpg` in tabs.

| Time | On screen | Narration |
|------|-----------|-----------|
| 0:00–0:20 | You on camera | "Hi, I'm Greg, Emediong Etuk Gregory. I'm a backend engineer from Nigeria with a computer engineering degree from the University of Uyo. This is TabCount, my entry to the OpenCV AI Competition 2026." |
| 0:20–0:50 | Hands counting tablets with a spatula; then the empty tray | "In community pharmacies and patent medicine stores here, tablets are dispensed loose and counted by hand, in fives, at the counter and again at stock-take. It's slow when the shop is busy, and every miscount loses money or short-changes a patient. Every pharmacy assistant already has a phone. TabCount turns that phone into a tablet counter." |
| 0:50–1:15 | Phone: open the live URL, tap **Take photo** on tray A, show the result | "This is the live app on AWS. I spread tablets on a dark cloth, take one photo… and in about a second: {{count}} tablets, high confidence. Every tablet is outlined and numbered, so I can check it at a glance." |
| 1:15–1:45 | Tray B (touching). Zoom into the result and the "Naive contour count" line | "Now the hard part: tablets touching each other. TabCount still finds {{count}}. Underneath, it shows the naive contour count, {{baseline}}, because a simple contour count merges every touching group into one. The watershed step is what splits them." |
| 1:45–2:00 | Tray C (stacked). Point at the orange outline and the warning | "If tablets overlap, it doesn't hide it. This orange outline is flagged as a possible cluster, counted as an estimate, and the confidence drops. The app tells me to check it." |
| 2:00–2:25 | Laptop: `docs/architecture.png` | "Architecture: the phone uploads to a FastAPI service in Docker on an Amazon EC2 t4g.small, which is an AWS Graviton arm64 instance. Results go to a private S3 bucket that deletes them after 60 days, logs go to CloudWatch, and the instance uses a least-privilege IAM role." |
| 2:25–2:45 | `docs/figures/pipeline_stages.png` | "The counting is classic OpenCV 5, no deep learning: flatten the lighting, Otsu threshold with automatic polarity, morphology, distance transform, seeds normalised per blob, then watershed, and finally a median-area check that catches crumbs and clusters." |
| 2:45–3:15 | `eval/results/real/summary.md` test table | "I evaluated on {{REAL_N}} real phone photos that I counted by hand twice, with a tune/test split. On the test photos TabCount was exactly right on {{REAL_EXACT}} and within one on {{REAL_WITHIN1}}. The naive contour method managed {{REAL_BASE_EXACT}}." |
| 3:15–3:30 | Scatter plot | "Each dot is a photo. Blue is TabCount, close to the diagonal; orange is the naive count, falling below it when tablets touch." |
| 3:30–3:45 | Failure contact sheet | "And here's where it fails: stacked tablets, glare, white tablets on white paper. These are the cases the confidence flags are designed to catch." |
| 3:45–4:15 | Back on camera, or the README limitations section | "Limitations: one layer, one tablet type, a contrasting background. It doesn't identify drugs, and it isn't a replacement for the pharmacist. It's a counting aid that shows its work so you can verify it. No personal data is collected, and stored photos are deleted after 60 days." |
| 4:15–4:30 | Live URL and GitHub repo on screen | "TabCount is live at {{LIVE_URL}}, and the code, evaluation data and report are on GitHub. Thanks for watching." |

**Checks before upload:** total length ≤ 5:00. Your face and name appear in the first 20 seconds. The
live URL is visible. No AWS console screens show account IDs or keys. Upload to YouTube as **Unlisted**.
