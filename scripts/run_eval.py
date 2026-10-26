"""TabCount evaluation: metrics, charts, failure gallery, optional deployed check.

    python scripts/run_eval.py --data eval/data/real
    python scripts/run_eval.py --data eval/data/synthetic
    python scripts/run_eval.py --data eval/data/real --url http://ELASTIC_IP

Protocol
--------
* Methods per image: `watershed` (default params, = deployed system),
  `watershed_no_cluster` (cluster correction off, ablation) and `baseline`
  (naive contour count on the identical preprocessing).
* peak_ratio is swept over [0.3, 0.4, 0.5, 0.6, 0.7] on the **tune** split only;
  the best value by MAE is reported as `watershed_tuned` on the **test** split.
  The code default is never changed automatically; a different best value is
  written to eval/results/tuned_params.json for a human decision.
* Headline metrics are computed on the **test** split only.
* --url sends every test image to the live endpoint and checks that counts match
  the local run exactly (proves the deployed system is the evaluated system).

Outputs go to eval/results/<dataset>/ and key charts are copied to docs/figures/.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.baseline import baseline_from_preprocessed  # noqa: E402
from app.counter import (ARCH, OPENCV_VERSION, CountParams, count_preprocessed,  # noqa: E402
                         preprocess)

SWEEP = [0.3, 0.4, 0.5, 0.6, 0.7]
METHODS = ["watershed", "watershed_no_cluster", "baseline"]
COLORS = {"watershed": "#2a78d6", "baseline": "#eb6834", "watershed_no_cluster": "#1baf7a",
          "watershed_tuned": "#6250d6"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_labels(data_dir: Path) -> list[dict]:
    path = data_dir / "labels.csv"
    if not path.exists():
        sys.exit(f"missing {path}")
    rows, skipped = [], 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            tc = (r.get("true_count") or "").strip()
            if not tc or not (data_dir / r["filename"]).exists():
                skipped += 1
                continue
            r["true_count"] = int(float(tc))
            r["background"] = (r.get("background") or "unknown").strip() or "unknown"
            r["condition"] = (r.get("condition") or "unknown").strip() or "unknown"
            r["split"] = (r.get("split") or "test").strip() or "test"
            r["source"] = (r.get("source") or data_dir.name).strip()
            rows.append(r)
    if skipped:
        print(f"note: skipped {skipped} rows without true_count or image file")
    return rows


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def metrics(true: list[int], pred: list[int]) -> dict:
    t, p = np.asarray(true, float), np.asarray(pred, float)
    if t.size == 0:
        return {"n": 0}
    err = p - t
    nz = t > 0
    return {
        "n": int(t.size),
        "exact_acc": round(float(np.mean(err == 0)), 4),
        "within1_acc": round(float(np.mean(np.abs(err) <= 1)), 4),
        "mae": round(float(np.mean(np.abs(err))), 3),
        "mape_pct": round(float(np.mean(np.abs(err[nz]) / t[nz]) * 100), 2) if nz.any() else None,
        "bias": round(float(np.mean(err)), 3),
    }


def breakdown(rows: list[dict], key: str, methods: list[str]) -> dict:
    out = {}
    for val in sorted({r[key] for r in rows}):
        sub = [r for r in rows if r[key] == val]
        out[val] = {m: metrics([r["true_count"] for r in sub], [r[m] for r in sub]) for m in methods}
    return out


def pct(vals, q):
    return round(float(np.percentile(vals, q)), 1) if len(vals) else None


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(INK2)
    ax.tick_params(colors=INK2)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def scatter_chart(rows, methods, path, title):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 5.4))
    t = [r["true_count"] for r in rows]
    hi = max(t + [max(r[m] for r in rows) for m in methods]) + 2
    ax.plot([0, hi], [0, hi], color=INK2, linewidth=1, linestyle="--", label="y = x (perfect)")
    for m, mk in zip(methods, ["o", "s", "^"]):
        ax.scatter(t, [r[m] for r in rows], s=36, marker=mk, color=COLORS[m], alpha=0.85,
                   edgecolors="white", linewidths=0.8, label=m.replace("_", " "))
    ax.set_xlim(0, hi); ax.set_ylim(0, hi)
    ax.set_xlabel("True count", color=INK); ax.set_ylabel("Predicted count", color=INK)
    ax.set_title(title, color=INK, fontsize=11)
    _style(ax)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def error_by_condition_chart(rows, methods, path, title):
    import matplotlib.pyplot as plt
    conds = sorted({r["condition"] for r in rows})
    fig, ax = plt.subplots(figsize=(7, 4.2))
    width = 0.8 / len(methods)
    x = np.arange(len(conds))
    for i, m in enumerate(methods):
        vals = [np.mean([abs(r[m] - r["true_count"]) for r in rows if r["condition"] == c]) for c in conds]
        bars = ax.bar(x + (i - (len(methods) - 1) / 2) * width, vals, width * 0.92,
                      color=COLORS[m], label=m.replace("_", " "))
        for b, v in zip(bars, vals):
            ax.annotate(f"{v:.1f}", (b.get_x() + b.get_width() / 2, v), ha="center", va="bottom",
                        fontsize=8, color=INK2, xytext=(0, 2), textcoords="offset points")
    ns = [sum(1 for r in rows if r["condition"] == c) for c in conds]
    ax.set_xticks(x, [f"{c}\n(n={n})" for c, n in zip(conds, ns)])
    ax.set_ylabel("Mean absolute error (tablets)", color=INK)
    ax.set_title(title, color=INK, fontsize=11)
    _style(ax); ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def latency_chart(lat, path, title):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.hist(lat, bins=min(30, max(5, len(lat) // 3)), color=COLORS["watershed"], edgecolor="white")
    for q, ls in [(50, "-"), (95, "--")]:
        v = np.percentile(lat, q)
        ax.axvline(v, color=INK, linestyle=ls, linewidth=1)
        ax.annotate(f"p{q} {v:.0f} ms", (v, ax.get_ylim()[1] * 0.92), xytext=(4, 0),
                    textcoords="offset points", fontsize=8, color=INK)
    ax.set_xlabel("Server-side pipeline time per image (ms)", color=INK)
    ax.set_ylabel("Images", color=INK)
    ax.set_title(title, color=INK, fontsize=11)
    _style(ax)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def contact_sheet(items: list[tuple[np.ndarray, str]], path: Path, cols: int = 4, tile_w: int = 400):
    tiles = []
    for img, cap in items:
        s = tile_w / img.shape[1]
        im = cv2.resize(img, (tile_w, int(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
        tiles.append((im, cap))
    tile_h = max(t[0].shape[0] for t in tiles) + 34
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.full((rows * tile_h, cols * tile_w, 3), 255, np.uint8)
    for i, (im, cap) in enumerate(tiles):
        r, c = divmod(i, cols)
        y, x = r * tile_h, c * tile_w
        sheet[y:y + im.shape[0], x:x + tile_w] = im
        cv2.putText(sheet, cap, (x + 6, y + im.shape[0] + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (20, 20, 20), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run_local(rows, data_dir, default: CountParams):
    """Preprocess once per image; run every method and every sweep value."""
    for i, r in enumerate(rows):
        data = (data_dir / r["filename"]).read_bytes()
        t0 = time.perf_counter()
        pre = preprocess(data, default)
        res = count_preprocessed(pre, default, t_start=t0 + pre.timings_ms["decode"] / 1000)
        r["watershed"] = res.count
        r["segments"] = res.segments
        r["clusters_flagged"] = res.clusters_flagged
        r["confidence"] = res.confidence
        r["warnings"] = ";".join(res.warnings)
        r["latency_ms"] = res.timings_ms["total"]
        r["watershed_no_cluster"] = count_preprocessed(pre, replace(default, cluster_correction=False)).count
        r["baseline"] = baseline_from_preprocessed(pre, default)
        for pr in SWEEP:
            r[f"peak_{pr}"] = res.count if pr == default.peak_ratio else \
                count_preprocessed(pre, replace(default, peak_ratio=pr)).count
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(rows)}")


def deployed_check(rows, data_dir, url: str) -> dict:
    import requests
    url = url.rstrip("/")
    health = requests.get(url + "/health", timeout=15).json()
    matches, lat, errors = 0, [], 0
    for r in rows:
        data = (data_dir / r["filename"]).read_bytes()
        ct = "image/png" if r["filename"].lower().endswith(".png") else "image/jpeg"
        t0 = time.perf_counter()
        try:
            resp = requests.post(url + "/api/count", files={"file": (r["filename"], data, ct)}, timeout=60)
            lat.append((time.perf_counter() - t0) * 1000)
            d = resp.json()
            r["deployed_count"] = d.get("count")
            r["deployed_baseline"] = d.get("baseline_count")
            r["deployed_server_ms"] = d.get("timings_ms", {}).get("total")
            ok = resp.status_code == 200 and d["count"] == r["watershed"] and d["baseline_count"] == r["baseline"]
            matches += int(ok)
        except Exception as exc:
            errors += 1
            r["deployed_count"] = f"error:{type(exc).__name__}"
    n = len(rows)
    return {"url": url, "health": health, "n": n, "matches": matches,
            "match_rate": round(matches / n, 4) if n else None, "errors": errors,
            "e2e_latency_ms": {"p50": pct(lat, 50), "p95": pct(lat, 95), "mean": round(float(np.mean(lat)), 1) if lat else None},
            "server_ms": {"p50": pct([r["deployed_server_ms"] for r in rows if isinstance(r.get("deployed_server_ms"), (int, float))], 50)}}


def md_table(title: str, table: dict, methods: list[str]) -> str:
    lines = [f"**{title}**", "", "| Method | n | Exact | Within ±1 | MAE | MAPE % | Bias |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for m in methods:
        s = table[m]
        if not s.get("n"):
            continue
        lines.append(f"| {m.replace('_', ' ')} | {s['n']} | {s['exact_acc']:.0%} | {s['within1_acc']:.0%} | "
                     f"{s['mae']:.2f} | {s['mape_pct'] if s['mape_pct'] is not None else '-'} | {s['bias']:+.2f} |")
    return "\n".join(lines)


def md_breakdown(title: str, bd: dict, method: str = "watershed") -> str:
    lines = [f"**{title}** (method: {method} vs baseline)", "",
             "| Group | n | Exact (ws) | MAE (ws) | MAE (baseline) |", "|---|---:|---:|---:|---:|"]
    for g, v in bd.items():
        lines.append(f"| {g} | {v[method]['n']} | {v[method]['exact_acc']:.0%} | {v[method]['mae']:.2f} | "
                     f"{v['baseline']['mae']:.2f} |")
    return "\n".join(lines)


def evaluate(data_dir: Path, out_root: Path, url: str | None, figures: Path) -> dict:
    dataset = data_dir.name
    label = "SYNTHETIC" if dataset.startswith("synth") else "REAL"
    out = out_root / dataset
    out.mkdir(parents=True, exist_ok=True)
    rows = load_labels(data_dir)
    if not rows:
        sys.exit(f"no labelled images in {data_dir}")
    default = CountParams()
    print(f"[{dataset}] {len(rows)} labelled images ({label}); running pipeline...")
    run_local(rows, data_dir, default)

    tune = [r for r in rows if r["split"] == "tune"]
    test = [r for r in rows if r["split"] == "test"]
    note = None
    if not test:
        test, note = rows, "no test split found: metrics computed on ALL images"
    sweep = {str(pr): metrics([r["true_count"] for r in tune], [r[f"peak_{pr}"] for r in tune])
             for pr in SWEEP} if tune else {}
    best = default.peak_ratio
    if tune:
        best = min(SWEEP, key=lambda pr: (sweep[str(pr)]["mae"], abs(pr - default.peak_ratio)))
    for r in rows:
        r["watershed_tuned"] = r[f"peak_{best}"]

    methods = list(METHODS) + (["watershed_tuned"] if best != default.peak_ratio else [])
    test_metrics = {m: metrics([r["true_count"] for r in test], [r[m] for r in test]) for m in methods}
    all_metrics = {m: metrics([r["true_count"] for r in rows], [r[m] for r in rows]) for m in methods}
    lat = [r["latency_ms"] for r in rows]

    tuned_path = out_root / "tuned_params.json"
    if best != default.peak_ratio:
        prev = json.loads(tuned_path.read_text()) if tuned_path.exists() else {}
        prev[dataset] = {"peak_ratio": best, "default_peak_ratio": default.peak_ratio,
                         "tune_mae_best": sweep[str(best)]["mae"],
                         "tune_mae_default": sweep[str(default.peak_ratio)]["mae"],
                         "note": "NOT applied to the code default; human decision required."}
        tuned_path.write_text(json.dumps(prev, indent=2))
        print(f"!! tuned peak_ratio={best} differs from default {default.peak_ratio}: see {tuned_path}")

    summary = {
        "dataset": dataset, "data_label": label, "n_images": len(rows),
        "n_tune": len(tune), "n_test": len(test), "split_note": note,
        "protocol": ("peak_ratio swept over %s on the tune split only; best by MAE; "
                     "headline metrics on the test split only. Default params = deployed system." % SWEEP),
        "default_params": asdict(default), "tuned_peak_ratio": best, "sweep_tune": sweep,
        "test": test_metrics, "all_images": all_metrics,
        "by_condition_test": breakdown(test, "condition", methods),
        "by_background_test": breakdown(test, "background", methods),
        "latency_ms": {"p50": pct(lat, 50), "p95": pct(lat, 95), "max": pct(lat, 100),
                       "note": "server-side pipeline time (timings_ms.total), local machine"},
        "machine": {"arch": ARCH, "opencv_version": OPENCV_VERSION},
        "confidence_counts_test": {c: sum(1 for r in test if r["confidence"] == c) for c in ("high", "medium", "low")},
        "accuracy_by_confidence_test": {c: metrics([r["true_count"] for r in test if r["confidence"] == c],
                                                   [r["watershed"] for r in test if r["confidence"] == c])
                                        for c in ("high", "medium", "low")},
    }

    if url:
        print(f"[{dataset}] deployed consistency check against {url} ...")
        summary["deployed_check"] = deployed_check(test, data_dir, url)
        dc = summary["deployed_check"]
        print(f"  match rate {dc['matches']}/{dc['n']}  e2e p50 {dc['e2e_latency_ms']['p50']} ms")

    # results.csv
    cols = ["filename", "true_count", "background", "condition", "split", "source", "watershed",
            "watershed_no_cluster", "baseline", "watershed_tuned", "segments", "clusters_flagged",
            "confidence", "warnings", "latency_ms"] + [f"peak_{p}" for p in SWEEP] + \
           (["deployed_count", "deployed_baseline", "deployed_server_ms"] if url else [])
    with open(out / "results.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    # charts
    title_sfx = f" ({label.lower()} {'test split' if not note else 'all'}, n={len(test)})"
    scatter_chart(test, ["watershed", "baseline"], out / "scatter_pred_vs_true.png",
                  "Predicted vs true count" + title_sfx)
    error_by_condition_chart(test, ["watershed", "watershed_no_cluster", "baseline"],
                             out / "error_by_condition.png", "Error by condition" + title_sfx)
    latency_chart(lat, out / "latency_hist.png", f"Pipeline latency ({label.lower()}, {ARCH}, n={len(lat)})")

    # failure gallery: 8 worst test images by |error| of the default method
    fdir = out / "failures"
    if fdir.exists():
        shutil.rmtree(fdir)
    fdir.mkdir()
    # only images that are actually wrong (up to 8), worst first
    worst = sorted((r for r in test if r["watershed"] != r["true_count"]),
                   key=lambda r: (-abs(r["watershed"] - r["true_count"]), r["filename"]))[:8]
    sheet = []
    for k, r in enumerate(worst, 1):
        res = count_preprocessed(preprocess((data_dir / r["filename"]).read_bytes(), default), default)
        img = cv2.imdecode(np.frombuffer(res.annotated_jpeg, np.uint8), cv2.IMREAD_COLOR)
        name = f"{k:02d}_{Path(r['filename']).stem}_true{r['true_count']}_pred{r['watershed']}.jpg"
        cv2.imwrite(str(fdir / name), img)
        sheet.append((img, f"{r['filename']}: true {r['true_count']} / pred {r['watershed']} [{r['condition']}]"))
    if sheet:
        contact_sheet(sheet, fdir / "failures_contact_sheet.jpg")

    # markdown
    md = [f"# Evaluation summary: {dataset} ({label})", "",
          f"Images: {len(rows)} labelled ({len(tune)} tune / {len(test)} test). {note or ''}", "",
          f"Protocol: {summary['protocol']}", "",
          md_table(f"Test split ({label.lower()})", test_metrics, methods), "",
          md_breakdown("By condition (test)", summary["by_condition_test"]), "",
          md_breakdown("By background (test)", summary["by_background_test"]), ""]
    if sweep:
        md += ["**peak_ratio sweep (tune split, watershed with cluster correction)**", "",
               "| peak_ratio | MAE | Exact |", "|---:|---:|---:|"]
        md += [f"| {p}{' (default)' if float(p) == default.peak_ratio else ''}{' (best)' if float(p) == best else ''} "
               f"| {v['mae']:.2f} | {v['exact_acc']:.0%} |" for p, v in sweep.items()]
        md.append("")
    md += [f"**Latency** (server-side pipeline, {ARCH}, OpenCV {OPENCV_VERSION}): "
           f"p50 {summary['latency_ms']['p50']} ms, p95 {summary['latency_ms']['p95']} ms.", ""]
    md += ["**Confidence vs accuracy (test, watershed)**", "", "| Confidence | n | Exact | MAE |", "|---|---:|---:|---:|"]
    for c, v in summary["accuracy_by_confidence_test"].items():
        if v.get("n"):
            md.append(f"| {c} | {v['n']} | {v['exact_acc']:.0%} | {v['mae']:.2f} |")
    md.append("")
    if url:
        dc = summary["deployed_check"]
        md += [f"**Deployed consistency check** ({dc['url']}, arch {dc['health'].get('arch')}, "
               f"OpenCV {dc['health'].get('opencv_version')}): {dc['matches']}/{dc['n']} test images "
               f"returned exactly the local counts (match rate {dc['match_rate']:.0%}); "
               f"end-to-end latency p50 {dc['e2e_latency_ms']['p50']} ms, p95 {dc['e2e_latency_ms']['p95']} ms.", ""]
    (out / "summary.md").write_text("\n".join(md))

    figures.mkdir(parents=True, exist_ok=True)
    for fn in ["scatter_pred_vs_true.png", "error_by_condition.png", "latency_hist.png"]:
        shutil.copy(out / fn, figures / f"{dataset}_{fn}")
    if sheet:
        shutil.copy(fdir / "failures_contact_sheet.jpg", figures / f"{dataset}_failures_contact_sheet.jpg")
    print(f"[{dataset}] done -> {out}")
    print("\n".join(md[6:8]))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", nargs="+", default=["eval/data/real"])
    ap.add_argument("--url", default=None, help="live endpoint for the deployed consistency check")
    ap.add_argument("--out", default="eval/results")
    ap.add_argument("--figures", default="docs/figures")
    a = ap.parse_args()
    for d in a.data:
        evaluate(Path(d), Path(a.out), a.url, Path(a.figures))


if __name__ == "__main__":
    main()
