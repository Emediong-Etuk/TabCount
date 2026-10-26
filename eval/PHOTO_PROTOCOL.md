# Photo protocol (real evaluation set)

Goal: **at least 30 photos** with hand-counted ground truth. More is better; 30 is fine.

## What to shoot

| Condition | Photos | What it looks like |
|-----------|-------:|--------------------|
| `separated` | ~10 | Tablets spread out, none touching |
| `touching`  | ~12 | Tablets pushed together in groups and chains, single layer |
| `stacked`   | ~4  | A few tablets partly on top of others (expected failures) |
| `hard`      | ~4  | Flash/glare, white tablets on white paper, broken halves, or two tablet types (expected failures) |

* **Counts:** spread between 5 and 60 tablets per photo (mix small and large counts).
* **Backgrounds** (split roughly half and half):
  * `dark`: black cloth, a dark tray or a dark book cover;
  * `light`: plain white paper.
* **Camera:** hold the phone 20–30 cm above, roughly top-down, tablets filling most of the frame.
  No flash, except in the deliberate glare shots.
* Use whatever tablets you have (vitamins, paracetamol, etc.). One type per photo except in `hard` shots.

## Ground truth

1. Count every photo by hand **twice**. If the two counts disagree, count a third time.
2. Note anything odd (a broken tablet, a crumb, a reflection) in `notes`.

## Steps

```powershell
# 1. Copy the photos from your phone into one folder, e.g. C:\photos\tabcount
# 2. Downscale + rename + create labels.csv
python scripts/prepare_real.py --src C:\photos\tabcount
# 3. Fill in eval/data/real/labels.csv (Excel is fine; keep it CSV):
#    true_count, background (dark/light), condition (separated/touching/stacked/hard), notes
#    Leave the split column as generated.
# 4. Evaluate
python scripts/run_eval.py --data eval/data/real
```

`prepare_real.py` names files `img_001.jpg`, `img_002.jpg`, … in the sorted order of your
original file names and records the mapping in `source_names.csv`.
iPhone HEIC photos must be exported as JPEG first (or set Camera → Formats → Most Compatible).
