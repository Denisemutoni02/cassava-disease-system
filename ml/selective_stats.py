"""Selective-prediction stats: what the DEPLOYED system does with its 0.60
confidence threshold (below it the API returns label='Uncertain' + soft advice).

Reads ml/models/run_real/test_predictions.json (produced by pick_demo_images.py)
and reports coverage / selective accuracy per threshold.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = json.loads((HERE / "models" / "run_real" / "test_predictions.json").read_text())
n = len(rows)

THRESHOLDS = [0.50, 0.55, 0.60, 0.65, 0.70]
print(f"n = {n} held-out test images\n")
print(f"{'thr':>5} {'coverage':>9} {'abstain':>8} {'acc@covered':>12} {'overall_correct':>16}")
for thr in THRESHOLDS:
    covered = [r for r in rows if r["conf"] >= thr]
    abst = n - len(covered)
    acc_cov = (sum(r["correct"] for r in covered) / len(covered)) if covered else 0.0
    # overall system accuracy counting abstentions as wrong (safe/reporting view)
    overall = sum(r["correct"] for r in covered) / n
    print(
        f"{thr:>5.2f} {len(covered)/n:>8.1%} {abst:>8d} {acc_cov:>12.4f} {overall:>16.4f}"
    )

# at the deployed threshold, where do the errors go?
thr = 0.60
covered = [r for r in rows if r["conf"] >= thr]
print(f"\nAt the deployed threshold {thr}:")
print(f"  classified : {len(covered)}  ({len(covered)/n:.1%})")
print(f"  abstained  : {n - len(covered)}  ({(n-len(covered))/n:.1%})  -> API returns 'Uncertain'")
print(f"  correct among classified: {sum(r['correct'] for r in covered)} "
      f"({sum(r['correct'] for r in covered)/len(covered):.4f} selective accuracy)")

# errors among covered, per true class
from collections import Counter

err = Counter(r["true"] for r in covered if not r["correct"])
print(f"  misclassified among classified, by true class: {dict(err)}")
