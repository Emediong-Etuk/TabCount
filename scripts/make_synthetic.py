"""Generate the synthetic tablet dataset (deterministic with --seed).

    python scripts/make_synthetic.py --n 200 --seed 42 --out eval/data/synthetic
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on sys.path

from tools.synthetic import make_dataset  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="eval/data/synthetic")
    a = ap.parse_args()
    labels = make_dataset(a.out, a.n, a.seed)
    print(f"wrote {a.n} synthetic images + {labels}")


if __name__ == "__main__":
    main()
