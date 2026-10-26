"""2x3 panel of pipeline stages for the report and video.

    python scripts/pipeline_figure.py eval/data/real/img_005.jpg
    python scripts/pipeline_figure.py eval/data/synthetic/syn_002.png --out docs/figures/pipeline_stages.png
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.counter import CountParams, count_tablets  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--out", default="docs/figures/pipeline_stages.png")
    a = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = Path(a.image).read_bytes()
    res = count_tablets(data, CountParams(), debug=True)

    def dec(b):
        return cv2.cvtColor(cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)

    orig = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    s = res.image["proc_w"] / orig.shape[1]
    orig = cv2.resize(orig, (res.image["proc_w"], res.image["proc_h"]), interpolation=cv2.INTER_AREA) if s < 1 else orig
    panels = [
        ("1. Input photo", cv2.cvtColor(orig, cv2.COLOR_BGR2RGB)),
        (f"2. Otsu mask ({res.polarity.replace('_', ' ')})", dec(res.debug_images["mask"])),
        ("3. Distance transform", dec(res.debug_images["distance"])),
        (f"4. Per-blob seeds (peak_ratio {res.params['peak_ratio']})", dec(res.debug_images["seeds"])),
        (f"5. Watershed labels ({res.segments} segments)", dec(res.debug_images["labels"])),
        (f"6. Result: count {res.count} ({res.confidence})", dec(res.debug_images["annotated"])),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.4))
    for ax, (title, img) in zip(axes.ravel(), panels):
        ax.imshow(img)
        ax.set_title(title, fontsize=12)
        ax.axis("off")
    fig.suptitle(f"TabCount OpenCV {res.opencv_version} pipeline ({Path(a.image).name}, "
                 f"{res.timings_ms['total']:.0f} ms on {res.arch})", fontsize=13)
    fig.tight_layout()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=150)
    print(f"wrote {a.out}: count={res.count} segments={res.segments} confidence={res.confidence}")


if __name__ == "__main__":
    main()
