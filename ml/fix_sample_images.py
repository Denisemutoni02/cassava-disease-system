"""Replace data/samples/*.jpg with real dataset images the deployed model
classifies correctly, so every documented curl / predict.py example shows a
sensible result during the demo.

Keeps the same three filenames (cmd_leaf.jpg, cbsd_leaf.jpg, healthy_leaf.jpg)
that README.md, docs/API.md and ml/predict.py already reference.

    E:\\cassava-disease-system\\venv\\Scripts\\python.exe fix_sample_images.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
PROJECT = ML_DIR.parent
SAMPLES = PROJECT / "data" / "samples"
sys.path.insert(0, str(PROJECT / "backend"))

from app.services.classifier import Classifier  # noqa: E402

# demo tray used picks[0:3]; take the next confident+correct one per class
DEMO_PICKS = {"CMD": 3, "CBSD": 3, "Healthy": 3}


def main() -> None:
    cand = json.loads((ML_DIR / "models" / "run_real" / "demo_candidates.json").read_text())
    clf = Classifier(PROJECT / "ml" / "models" / "mobilenetv2_cassava.onnx", force_mock=False)

    for cls, fname in (("CMD", "cmd_leaf.jpg"), ("CBSD", "cbsd_leaf.jpg"), ("Healthy", "healthy_leaf.jpg")):
        rows = cand["picks"][cls]
        idx = DEMO_PICKS[cls]
        if idx >= len(rows):
            print(f"  ! no spare candidate for {cls}, keeping existing {fname}")
            continue
        src = Path(rows[idx]["path"])
        dst = SAMPLES / fname
        shutil.copy2(src, dst)
        pred = clf.predict(dst.read_bytes())
        mark = "OK" if pred.label == cls else "MISMATCH"
        print(f"  [{mark}] {fname} <- {src.name}  -> {pred.label} conf={pred.confidence:.3f}")

    print("\nFinal check of data/samples/:")
    for p in sorted(SAMPLES.glob("*.jpg")):
        pred = clf.predict(p.read_bytes())
        print(f"  {p.name:<20} -> {pred.label:<8} conf={pred.confidence:.3f}")


if __name__ == "__main__":
    main()
