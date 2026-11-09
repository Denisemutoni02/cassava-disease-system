"""Assemble and verify the live-demo image tray.

Copies 3 confidently-correct held-out images per class plus one deliberately
low-confidence image into ``data/demo/`` with self-describing names, then
runs each tray image (and the existing ``data/samples``) through the deployed
model so the demo script can quote exact expected outputs.

    E:\\cassava-disease-system\\venv\\Scripts\\python.exe build_demo_tray.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
PROJECT = ML_DIR.parent
DEMO_DIR = PROJECT / "data" / "demo"
sys.path.insert(0, str(PROJECT / "backend"))

from app.services.classifier import Classifier  # noqa: E402


def main() -> None:
    cand = json.loads((ML_DIR / "models" / "run_real" / "demo_candidates.json").read_text())
    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    # --- copy selected images with demo-friendly names ---------------------
    plan: list[tuple[Path, str]] = []
    for cls, key in (("CBSD", "cbsd"), ("CMD", "cmd"), ("Healthy", "healthy")):
        for i, row in enumerate(cand["picks"][cls][:3], start=1):
            plan.append((Path(row["path"]), f"demo_{key}_{i}.jpg"))
    if cand["low"]:
        plan.append((Path(cand["low"][1]["path"]), "demo_low_confidence.jpg"))

    for src, name in plan:
        if src.exists():
            shutil.copy2(src, DEMO_DIR / name)

    # --- verify every demo/sample image through the deployed model ---------
    clf = Classifier(PROJECT / "ml" / "models" / "mobilenetv2_cassava.onnx", force_mock=False)
    print(f"Classifier: {clf.mode} ({clf.version_tag})\n")
    rows = []
    for folder in (DEMO_DIR, PROJECT / "data" / "samples"):
        if not folder.exists():
            continue
        for p in sorted(folder.glob("*.jpg")):
            pred = clf.predict(p.read_bytes())
            rows.append((p, pred))
            flag = "" if pred.confidence >= 0.60 else "  <- soft advice (conf < 0.60)"
            print(
                f"  {p.parent.name}/{p.name:<26} -> {pred.label:<8} "
                f"conf={pred.confidence:.3f}{flag}"
            )

    print(f"\nDemo tray: {len(list(DEMO_DIR.glob('*.jpg')))} images in data/demo/")
    print(f"Samples  : {len(list((PROJECT / 'data' / 'samples').glob('*.jpg')))} images in data/samples/")

    # machine-readable manifest for the demo script / report
    out = {
        "images": [
            {
                "file": str(p.relative_to(PROJECT)).replace("\\", "/"),
                "predicted_label": pr.label,
                "confidence": pr.confidence,
                "advice_is_soft": pr.confidence < 0.60,
            }
            for p, pr in rows
        ]
    }
    (DEMO_DIR / "manifest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {DEMO_DIR / 'manifest.json'}")


if __name__ == "__main__":
    main()
