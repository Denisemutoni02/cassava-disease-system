"""Scan the held-out test manifest and rank images by model confidence.

Used to pick reliable live-demo photos (model predicts the true class with
high confidence) — and to find one honest low-confidence example.

    E:\\cassava-disease-system\\venv\\Scripts\\python.exe pick_demo_images.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
PROJECT = ML_DIR.parent
sys.path.insert(0, str(PROJECT / "backend"))

from app.services.classifier import Classifier  # noqa: E402

CLASS_NAMES = ["CBSD", "CMD", "Healthy"]


def main() -> None:
    manifest = ML_DIR / "models" / "run_real" / "test_manifest.csv"
    clf = Classifier(PROJECT / "ml" / "models" / "mobilenetv2_cassava.onnx", force_mock=False)

    rows = []
    with manifest.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            p = Path(row["image_path"])
            if not p.exists():
                p = PROJECT / "data" / "cassava" / p.parent.name / p.name
            if not p.exists():
                continue
            pred = clf.predict(p.read_bytes())
            rows.append(
                {
                    "path": str(p),
                    "true": row["label"],
                    "pred": pred.label,
                    "conf": pred.confidence,
                    "correct": pred.label == row["label"],
                }
            )

    out = ML_DIR / "models" / "run_real" / "test_predictions.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {out}  ({len(rows)} images)")

    # Top-6 confident CORRECT per class (candidates for the demo tray)
    print("\nTop confident+correct candidates per class:")
    picks = {}
    for cls in CLASS_NAMES:
        good = [r for r in rows if r["true"] == cls and r["correct"]]
        good.sort(key=lambda r: -r["conf"])
        picks[cls] = good[:6]
        print(f"  {cls}: {len(good)} correct of {sum(1 for r in rows if r['true']==cls)}")
        for r in good[:3]:
            print(f"     {r['conf']:.3f}  {Path(r['path']).name}")

    # Low-confidence examples (for demonstrating soft advice)
    low = sorted([r for r in rows if r["conf"] < 0.55], key=lambda r: r["conf"])[:5]
    print("\nLow-confidence examples (for the soft-advice demo):")
    for r in low:
        print(f"     {r['conf']:.3f}  true={r['true']}  pred={r['pred']}  {Path(r['path']).name}")

    (ML_DIR / "models" / "run_real" / "demo_candidates.json").write_text(
        json.dumps({"picks": picks, "low": low}, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
