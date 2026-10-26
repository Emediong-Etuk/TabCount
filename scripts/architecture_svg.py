"""Hand-authored architecture diagram -> docs/architecture.svg.

    python scripts/architecture_svg.py
(docs/architecture.png is a 2x screenshot of the SVG; docs/architecture.mmd is the Mermaid source.)
"""
from pathlib import Path
from html import escape as e
W, H = 1220, 840
out = []
def rect(x, y, w, h, fill, stroke, sw=1.5, rx=10, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')
def text(x, y, s, size=13, weight=400, fill="#0b0b0b", anchor="middle", mono=False):
    fam = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" if mono else "Inter,Segoe UI,Helvetica,Arial,sans-serif"
    out.append(f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{e(s)}</text>')
def box(x, y, w, h, lines, fill, stroke, title_fill="#0b0b0b", sw=1.5):
    rect(x, y, w, h, fill, stroke, sw)
    n = len(lines); top = y + h / 2 - (n - 1) * 8.5 + 4
    for i, (s, kind) in enumerate(lines):
        if kind == "t": text(x + w / 2, top + i * 17, s, 13, 700, title_fill)
        elif kind == "m": text(x + w / 2, top + i * 17, s, 11, 400, "#33415c", mono=True)
        else: text(x + w / 2, top + i * 17, s, 12, 400, "#3b3a37")
def arrow(points, label=None, lx=None, ly=None, dash=None, color="#3b3a37"):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    pts = " ".join(f"{x},{y}" for x, y in points)
    out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6" marker-end="url(#ah)"{d}/>')
    if label:
        tw = len(label) * 6.4 + 10
        out.append(f'<rect x="{lx - tw/2}" y="{ly - 12}" width="{tw}" height="17" rx="4" fill="#ffffff" opacity="0.92"/>')
        text(lx, ly + 1, label, 11, 500, "#3b3a37")

BLUE, BLUE_BG = "#2a78d6", "#eaf2fc"
ORANGE, ORANGE_BG = "#e47911", "#fff4e5"
GREEN, GREEN_BG = "#0b6e4f", "#e9f6ef"
GREY, GREY_BG = "#52514e", "#f4f4f2"

out.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
text(W / 2, 32, "TabCount architecture: OpenCV 5 pipeline on AWS", 18, 700)

# clients
box(20, 200, 200, 110, [("Phone browser", "t"), ("index.html (vanilla JS)", "s"), ("resizes to 1600 px JPEG", "s"), ("before upload", "s")], GREY_BG, GREY)
box(20, 470, 200, 100, [("Eval & benchmark", "t"), ("run_eval.py --url", "m"), ("benchmark.py", "m")], GREY_BG, GREY)

# AWS frame
rect(250, 52, 955, 772, "#fffaf3", ORANGE, 2.2, 14)
text(270, 76, "AWS Region eu-west-1", 14, 700, "#b45309", "start")
# EC2
rect(268, 88, 920, 540, ORANGE_BG, ORANGE, 1.6, 12)
text(286, 112, "Amazon EC2 t4g.small  |  AWS Graviton (arm64)  |  Amazon Linux 2023  |  Elastic IP  |  IMDSv2 required, hop limit 2", 12.5, 600, "#7c3a00", "start")
# Docker
rect(286, 124, 884, 486, "#ffffff", GREY, 1.3, 10, "6 4")
text(302, 146, "Docker container \"tabcount\"  (port 80 -> 8000, restart unless-stopped, awslogs log driver)", 12, 500, GREY, "start")
# FastAPI
box(304, 250, 200, 120, [("FastAPI + uvicorn", "t"), ("POST /api/count", "m"), ("GET /health", "m"), ("GET /api/results/{id}", "m"), ("2 workers", "s")], GREEN_BG, GREEN, "#0b3d2c")
# OpenCV pipeline frame
px, py, pw, ph = 540, 160, 615, 432
rect(px, py, pw, ph, BLUE_BG, BLUE, 2.2, 12)
text(px + 14, py + 22, "OpenCV 5.0 pipeline  (app/counter.py, core + imgproc only)", 13, 700, "#0b2a4f", "start")
steps = [
    ("1 Decode + resize", "imdecode, resize(INTER_AREA)"),
    ("2 Gray, blur, flatten light", "cvtColor, GaussianBlur"),
    ("3 Otsu + polarity", "threshold(OTSU), border band"),
    ("6 Per-blob seeds", "connectedComponents"),
    ("5 Distance transform", "distanceTransform(DIST_L2)"),
    ("4 Morphology + hole fill", "morphologyEx, findContours"),
    ("7 Marker watershed", "watershed, dilate"),
    ("8 Area / debris / cluster", "bincount stats, median area"),
    ("9 Annotate + encode", "drawContours, putText"),
]
bw, bh, gx, gy = 185, 76, 15, 38
pos = {}
for i, (t, m) in enumerate(steps):
    r, c = divmod(i, 3)
    x = px + 16 + c * (bw + gx); y = py + 40 + r * (bh + gy)
    rect(x, y, bw, bh, "#ffffff", BLUE, 1.4, 8)
    text(x + bw / 2, y + 32, t, 12.5, 700, "#0b2a4f")
    text(x + bw / 2, y + 52, m, 10.5, 400, "#33415c", mono=True)
    pos[t[0]] = (x, y)
def mid_r(k): x, y = pos[k]; return (x + bw, y + bh / 2)
def mid_l(k): x, y = pos[k]; return (x, y + bh / 2)
def mid_b(k): x, y = pos[k]; return (x + bw / 2, y + bh)
def mid_t(k): x, y = pos[k]; return (x + bw / 2, y)
arrow([mid_r("1"), mid_l("2")]); arrow([mid_r("2"), mid_l("3")])
arrow([mid_b("3"), mid_t("4")])
arrow([mid_l("4"), mid_r("5")]); arrow([mid_l("5"), mid_r("6")])
arrow([mid_b("6"), mid_t("7")])
arrow([mid_r("7"), mid_l("8")]); arrow([mid_r("8"), mid_l("9")])

# FastAPI <-> pipeline
arrow([(504, 275), (522, 275), (522, mid_l("1")[1]), mid_l("1")], "bytes", 522, 236)
x9, y9 = mid_b("9")
arrow([(x9, y9), (x9, 600 - 8 + 0), (440, 592), (440, 370)], "count, confidence, annotated JPEG", 760, 594)

# clients -> api
arrow([(220, 240), (304, 280)], "POST photo", 258, 236)
arrow([(304, 318), (220, 290)], "JSON result", 256, 322)
arrow([(220, 520), (262, 520), (262, 355), (304, 355)], "HTTP", 262, 450)

# bottom row AWS services
box(268, 680, 270, 120, [("IAM role tabcount-ec2-role", "t"), ("instance profile, least privilege:", "s"), ("s3:Put/GetObject on requests/*", "m"), ("logs:* (4 actions) on /tabcount/app", "m")], ORANGE_BG, ORANGE, "#7c3a00")
box(575, 680, 290, 120, [("Amazon S3 (private)", "t"), ("requests/yyyy/mm/dd/{id}/", "m"), ("input, annotated.jpg, result.json", "s"), ("SSE-S3, public access blocked,", "s"), ("lifecycle: delete after 60 days", "s")], ORANGE_BG, ORANGE, "#7c3a00")
box(900, 680, 288, 120, [("Amazon CloudWatch Logs", "t"), ("/tabcount/app, 30-day retention", "m"), ("one JSON line per request", "s"), ("(no images, no IPs)", "s"), ("Logs Insights: p50/p95 latency", "s")], ORANGE_BG, ORANGE, "#7c3a00")
arrow([(330, 680), (330, 628)], "IMDSv2 credentials", 330, 655, dash="5 4")
arrow([(475, 370), (475, 660), (720, 660), (720, 680)], "BackgroundTask PutObject", 600, 661)
arrow([(1044, 610), (1044, 680)], "stdout -> awslogs", 1044, 655)

# legend
ly = 360
text(20, ly, "Legend", 13, 700, anchor="start")
for i, (fill, stroke, label) in enumerate([(BLUE_BG, BLUE, "OpenCV 5 components"), (ORANGE_BG, ORANGE, "AWS components"), (GREEN_BG, GREEN, "Web app (Python)"), (GREY_BG, GREY, "Clients")]):
    rect(20, ly + 12 + i * 24, 18, 14, fill, stroke, 1.5, 3)
    text(46, ly + 24 + i * 24, label, 12, 400, "#3b3a37", "start")

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
       '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
       '<path d="M0,0 L10,5 L0,10 z" fill="#3b3a37"/></marker></defs>' + "".join(out) + "</svg>")
(Path(__file__).resolve().parents[1] / "docs" / "architecture.svg").write_text(svg)
print("ok")
