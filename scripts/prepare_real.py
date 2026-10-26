"""Prepare real phone photos for evaluation.

Writes downscaled copies (longest side 1600 px, JPEG q90, EXIF orientation
applied) to eval/data/real/ and creates labels.csv for you to fill in.

    python scripts/prepare_real.py --src path/to/raw_photos [--out eval/data/real]

Existing labels in labels.csv are kept; only new files are appended.
Files are renamed img_001.jpg, img_002.jpg, ... in sorted order of the source
names (a mapping is written to eval/data/real/source_names.csv, which is not
needed for evaluation).
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from tools.synthetic import LABEL_COLUMNS, split_for  # noqa: E402

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def load_oriented(path: Path):
    # IMREAD_COLOR applies the EXIF orientation tag (OpenCV default behaviour).
    data = np.fromfile(str(path), np.uint8)  # works with non-ASCII paths on Windows
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="folder with your original photos")
    ap.add_argument("--out", default="eval/data/real")
    ap.add_argument("--max-side", type=int, default=1600)
    a = ap.parse_args()

    src, out = Path(a.src), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in src.iterdir() if p.suffix.lower() in EXTS)
    if not files:
        sys.exit(f"no images found in {src}")
    if any(p.suffix.lower() in (".heic", ".heif") for p in src.iterdir()):
        print("NOTE: HEIC files are skipped; export them as JPEG first.")

    labels_path = out / "labels.csv"
    existing = {}
    if labels_path.exists():
        with open(labels_path, newline="") as f:
            existing = {r["filename"]: r for r in csv.DictReader(f)}

    rows, mapping = [], []
    for i, p in enumerate(files):
        name = f"img_{i + 1:03d}.jpg"
        img = load_oriented(p)
        if img is None:
            print(f"skip (unreadable): {p.name}")
            continue
        h, w = img.shape[:2]
        s = min(1.0, a.max_side / max(h, w))
        if s < 1.0:
            img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        buf.tofile(str(out / name))
        mapping.append({"filename": name, "source_name": p.name})
        rows.append(existing.get(name) or {"filename": name, "true_count": "", "background": "",
                                           "condition": "", "split": split_for(i), "notes": "",
                                           "source": "real"})
        print(f"{p.name} -> {name} ({img.shape[1]}x{img.shape[0]})")

    with open(labels_path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=LABEL_COLUMNS, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    with open(out / "source_names.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["filename", "source_name"])
        wr.writeheader()
        wr.writerows(mapping)
    print(f"\n{len(rows)} images in {out}. Now fill in true_count, background (dark/light), "
          f"condition (separated/touching/stacked/hard) and notes in {labels_path}.")


if __name__ == "__main__":
    main()
