"""Held-out evaluation of the DEPLOYED classifier.

Runs the exact production inference path (``backend/app/services/classifier``)
over every image in the held-out test manifest and reports the metrics needed
for the research report:

  * accuracy, per-class precision / recall / F1, macro + weighted averages
  * confusion matrix (rows = true, cols = predicted)
  * mean / std model confidence, and how often confidence >= threshold
  * single-image inference latency (ms) on this machine

Usage (from the ``ml/`` directory, Windows venv)::

    E:\\cassava-disease-system\\venv\\Scripts\\python.exe evaluate_onnx.py
    E:\\cassava-disease-system\\venv\\Scripts\\python.exe evaluate_onnx.py --json out.json

The test manifest (``models/run_real/test_manifest.csv``) is the 15% split
held out at training time (seed 42) and never seen during training.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
PROJECT = ML_DIR.parent
BACKEND = PROJECT / "backend"
# Reuse the production preprocessing + ONNX session so numbers match the API.
sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402

from app.services.classifier import Classifier  # noqa: E402

CLASS_NAMES = ["CBSD", "CMD", "Healthy"]  # same order as the model output


def load_manifest(path: Path) -> list[tuple[Path, str]]:
    rows: list[tuple[Path, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            p = Path(row["image_path"])
            if not p.exists():
                # manifest stores Windows paths; fall back to a local rebuild
                p = PROJECT / "data" / "cassava" / p.parent.name / p.name
            if p.exists() and row["label"] in CLASS_NAMES:
                rows.append((p, row["label"]))
    return rows


def evaluate(model_path: Path, manifest: Path) -> dict:
    clf = Classifier(model_path, force_mock=False)
    if clf.mode == "mock":
        raise SystemExit(f"Refusing to evaluate: mock classifier (model {model_path} missing?)")

    items = load_manifest(manifest)
    if not items:
        raise SystemExit(f"No images found from manifest {manifest}")

    y_true: list[int] = []
    y_pred: list[int] = []
    confidences: list[float] = []
    latencies: list[float] = []

    for path, label in items:
        data = path.read_bytes()
        t0 = time.perf_counter()
        pred = clf.predict(data)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        y_true.append(CLASS_NAMES.index(label))
        y_pred.append(CLASS_NAMES.index(pred.label))
        confidences.append(pred.confidence)

    y_true_a = np.array(y_true)
    y_pred_a = np.array(y_pred)
    n = len(y_true)

    # --- confusion matrix + per-class metrics (no sklearn dependency) ------
    cm = np.zeros((len(CLASS_NAMES), len(CLASS_NAMES)), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1

    per_class = {}
    for i, cls in enumerate(CLASS_NAMES):
        tp = cm[i, i]
        fp = cm[:, i].sum() - tp
        fn = cm[i, :].sum() - tp
        support = int(cm[i, :].sum())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[cls] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }

    def macro(key: str) -> float:
        return round(sum(per_class[c][key] for c in CLASS_NAMES) / len(CLASS_NAMES), 4)

    weighted = {
        key: round(
            sum(per_class[c][key] * per_class[c]["support"] for c in CLASS_NAMES) / n, 4
        )
        for key in ("precision", "recall", "f1")
    }

    acc = round(float((y_true_a == y_pred_a).mean()), 4)
    conf = np.array(confidences)

    # --- latency ------------------------------------------------------------
    lat = np.array(latencies)
    latency = {
        "n": int(lat.size),
        "mean_ms": round(float(lat.mean()), 2),
        "median_ms": round(float(np.median(lat)), 2),
        "p95_ms": round(float(np.percentile(lat, 95)), 2),
        "min_ms": round(float(lat.min()), 2),
        "max_ms": round(float(lat.max()), 2),
    }

    # --- model artefact sizes ----------------------------------------------
    sizes = {}
    for name, p in {
        "keras_float": PROJECT / "ml" / "models" / "run_real" / "best_model.keras",
        "tflite_dynamic": PROJECT / "ml" / "models" / "mobilenetv2_cassava_dynamic.tflite",
        "onnx_deployed": model_path,
    }.items():
        if p.exists():
            sizes[name] = {
                "file": str(p.relative_to(PROJECT)).replace("\\", "/"),
                # decimal MB, same convention as quantise.py's report
                "size_mb": round(p.stat().st_size / 1_000_000, 3),
            }

    return {
        "model": {
            "file": str(model_path).replace("\\", "/"),
            "mode": clf.mode,
            "version_tag": clf.version_tag,
            "classes": CLASS_NAMES,
        },
        "dataset": {
            "manifest": str(manifest).replace("\\", "/"),
            "n_images": n,
            "split": "held-out test split (15%, seed 42, never trained on)",
            "per_class_support": {c: per_class[c]["support"] for c in CLASS_NAMES},
        },
        "metrics": {
            "accuracy": acc,
            "macro_precision": macro("precision"),
            "macro_recall": macro("recall"),
            "macro_f1": macro("f1"),
            "weighted_precision": weighted["precision"],
            "weighted_recall": weighted["recall"],
            "weighted_f1": weighted["f1"],
            "per_class": per_class,
            "confusion_matrix": {
                "labels": CLASS_NAMES,
                "rows_true_cols_pred": cm.tolist(),
            },
            "confidence": {
                "mean": round(float(conf.mean()), 4),
                "std": round(float(conf.std()), 4),
                "min": round(float(conf.min()), 4),
                "max": round(float(conf.max()), 4),
                "pct_at_or_above_0.60": round(float((conf >= 0.60).mean()) * 100, 1),
            },
        },
        "inference_latency": latency,
        "model_sizes": sizes,
    }


def print_report(res: dict) -> None:
    m = res["metrics"]
    print("=" * 66)
    print(f"Held-out evaluation — {res['model']['version_tag']}  ({res['model']['mode']})")
    print("=" * 66)
    print(f"Images          : {res['dataset']['n_images']}  {res['dataset']['per_class_support']}")
    print(f"Accuracy        : {m['accuracy']:.4f}")
    print(f"Macro P / R / F1: {m['macro_precision']:.4f} / {m['macro_recall']:.4f} / {m['macro_f1']:.4f}")
    print(
        f"Weighted  P / R / F1: {m['weighted_precision']:.4f} / {m['weighted_recall']:.4f} / {m['weighted_f1']:.4f}"
    )
    print("\nPer-class:")
    print(f"  {'class':<9}{'prec':>8}{'recall':>8}{'f1':>8}{'support':>9}")
    for c in res["model"]["classes"]:
        pc = m["per_class"][c]
        print(f"  {c:<9}{pc['precision']:>8.4f}{pc['recall']:>8.4f}{pc['f1']:>8.4f}{pc['support']:>9d}")
    cm = m["confusion_matrix"]["rows_true_cols_pred"]
    labels = m["confusion_matrix"]["labels"]
    print("\nConfusion matrix (rows = true, cols = predicted):")
    print(f"  {'':>9}" + "".join(f"{c:>9}" for c in labels))
    for i, row in enumerate(cm):
        print(f"  {labels[i]:>9}" + "".join(f"{v:>9d}" for v in row))
    conf = m["confidence"]
    print(
        f"\nConfidence: mean={conf['mean']:.4f}  sd={conf['std']:.4f}  "
        f"min={conf['min']:.4f}  max={conf['max']:.4f}  "
        f">=0.60 threshold: {conf['pct_at_or_above_0.60']}%"
    )
    lat = res["inference_latency"]
    print(
        f"\nInference latency (single image, batch=1): "
        f"mean={lat['mean_ms']:.1f} ms  median={lat['median_ms']:.1f} ms  "
        f"p95={lat['p95_ms']:.1f} ms  (n={lat['n']})"
    )
    print("\nModel sizes:")
    for name, info in res["model_sizes"].items():
        print(f"  {name:<16}{info['size_mb']:>8.3f} MB   {info['file']}")
    print("=" * 66)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--model",
        default=str(PROJECT / "ml" / "models" / "mobilenetv2_cassava.onnx"),
        help="model artefact to evaluate (default: the deployed ONNX)",
    )
    ap.add_argument(
        "--manifest",
        default=str(ML_DIR / "models" / "run_real" / "test_manifest.csv"),
        help="held-out test manifest CSV",
    )
    ap.add_argument("--json", help="also write the full result to this JSON file")
    args = ap.parse_args()

    res = evaluate(Path(args.model), Path(args.manifest))
    print_report(res)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
