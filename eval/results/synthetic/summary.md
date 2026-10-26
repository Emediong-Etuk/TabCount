# Evaluation summary: synthetic (SYNTHETIC)

Images: 200 labelled (67 tune / 133 test). 

Protocol: peak_ratio swept over [0.3, 0.4, 0.5, 0.6, 0.7] on the tune split only; best by MAE; headline metrics on the test split only. Default params = deployed system.

**Test split (synthetic)**

| Method | n | Exact | Within ±1 | MAE | MAPE % | Bias |
|---|---:|---:|---:|---:|---:|---:|
| watershed | 133 | 98% | 99% | 0.04 | 0.09 | -0.04 |
| watershed no cluster | 133 | 79% | 82% | 1.20 | 3.06 | -1.20 |
| baseline | 133 | 29% | 30% | 12.21 | 34.88 | -12.21 |
| watershed tuned | 133 | 100% | 100% | 0.00 | 0.0 | +0.00 |

**By condition (test)** (method: watershed vs baseline)

| Group | n | Exact (ws) | MAE (ws) | MAE (baseline) |
|---|---:|---:|---:|---:|
| mixed | 44 | 98% | 0.02 | 11.43 |
| separated | 39 | 100% | 0.00 | 0.00 |
| touching | 50 | 96% | 0.10 | 22.42 |

**By background (test)** (method: watershed vs baseline)

| Group | n | Exact (ws) | MAE (ws) | MAE (baseline) |
|---|---:|---:|---:|---:|
| dark | 56 | 100% | 0.00 | 13.16 |
| light | 77 | 96% | 0.08 | 11.52 |

**peak_ratio sweep (tune split, watershed with cluster correction)**

| peak_ratio | MAE | Exact |
|---:|---:|---:|
| 0.3 | 4.76 | 67% |
| 0.4 | 0.70 | 91% |
| 0.5 (default) | 0.01 | 99% |
| 0.6 (best) | 0.00 | 100% |
| 0.7 | 0.00 | 100% |

**Latency** (server-side pipeline, x86_64, OpenCV 5.0.0): p50 78.0 ms, p95 99.7 ms.

**Confidence vs accuracy (test, watershed)**

| Confidence | n | Exact | MAE |
|---|---:|---:|---:|
| high | 105 | 100% | 0.00 |
| medium | 14 | 100% | 0.00 |
| low | 14 | 79% | 0.43 |
