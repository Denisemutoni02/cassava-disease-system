"""Post-training quantisation + full comparison report.

Converts the best trained model to:
  1. TFLite dynamic-range (int8 weights, float activations) — default
  2. TFLite full-integer int8 (optional --full-int8, needs calibration images)
  3. ONNX (optional --onnx, auto-skipped if tf2onnx missing)

For every produced artefact, measures on the held-out test set:
  • file size (MB)          • test accuracy & macro-F1 (+ per-class F1)
  • mean inference latency (ms)

Writes ``quantisation_report.json`` next to the output models and prints a
comparison table.

Usage
-----
    python quantise.py --model models/run/best_model.keras \
                       --test-manifest models/run/test_manifest.csv
    python quantise.py ... --full-int8 --data-for-calibration ../data/cassava
    python quantise.py ... --onnx
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from cassava_dataset import read_manifest
from common import CLASS_NAMES, save_json, set_seed
from inference import InferenceEngine, preprocess


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------


def evaluate_engine(engine: InferenceEngine, manifest_paths: list[str], labels: list[int]) -> dict:
    """Accuracy, macro/per-class F1 and latency for one artefact."""
    from sklearn.metrics import accuracy_score, f1_score, classification_report

    preds: list[int] = []
    for path in manifest_paths:
        probs = engine.predict_batch(preprocess(path))[0]
        preds.append(int(np.argmax(probs)))

    report = classification_report(
        labels, preds, target_names=CLASS_NAMES, output_dict=True, zero_division=0
    )
    return {
        "accuracy": float(accuracy_score(labels, preds)),
        "f1_macro": float(f1_score(labels, preds, average="macro", zero_division=0)),
        "per_class_f1": {c: round(report[c]["f1-score"], 4) for c in CLASS_NAMES},
        "latency_ms": round(engine.latency_ms(), 2),
    }


def file_size_mb(path: Path) -> float:
    return round(path.stat().st_size / 1e6, 3)


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def to_tflite(model_path: Path, out_path: Path, full_int8: bool, calibration_paths: list[str]) -> None:
    import tensorflow as tf

    model = tf.keras.models.load_model(model_path)
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]

    if full_int8:
        def representative_dataset():
            for p in calibration_paths[:100]:
                yield [preprocess(p).astype(np.float32)]

        converter.representative_dataset = representative_dataset
        converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        converter.inference_input_type = tf.uint8
        converter.inference_output_type = tf.uint8

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(converter.convert())


def to_onnx(model_path: Path, out_path: Path) -> bool:
    """Export via tf2onnx CLI. Returns False when tf2onnx is unavailable."""
    import shutil
    import subprocess
    import sys

    import tensorflow as tf

    if shutil.which("tf2onnx") is None and not _module_exists("tf2onnx"):
        return False

    tmp_dir = out_path.parent / "_onnx_tmp_savedmodel"
    tf.keras.models.load_model(model_path).export(tmp_dir)
    cmd = [
        sys.executable, "-m", "tf2onnx.convert",
        "--saved-model", str(tmp_dir),
        "--output", str(out_path),
        "--opset", "13",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    finally:
        import shutil as _sh

        _sh.rmtree(tmp_dir, ignore_errors=True)


def _module_exists(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--model", default="models/run/best_model.keras", help="Full-precision model")
    p.add_argument("--test-manifest", default="models/run/test_manifest.csv",
                   help="Test split CSV (image_path,label) produced by train_mobilenetv2.py")
    p.add_argument("--output-dir", default="models", help="Where quantised artefacts are written")
    p.add_argument("--full-int8", action="store_true", help="Full-integer TFLite (uint8 in/out)")
    p.add_argument("--data-for-calibration", default=None,
                   help="Image root/CSV for int8 calibration (defaults to the test manifest images)")
    p.add_argument("--onnx", action="store_true", help="Also export ONNX (needs tf2onnx + onnx)")
    p.add_argument("--no-eval", action="store_true", help="Skip test-set evaluation (conversion only)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    set_seed(args.seed)
    model_path = Path(args.model)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = read_manifest(Path(args.test_manifest))
    print(f"[quantise] model:        {model_path}")
    print(f"[quantise] test images:  {len(manifest.paths)}")
    print(f"[quantise] class order:  {CLASS_NAMES}")

    artefacts: list[tuple[str, Path]] = []

    # ---------------- baseline (float) ----------------
    if not args.no_eval:
        print("\n[baseline] evaluating full-precision model …")
        float_engine = InferenceEngine(model_path)
        results = {
            "float": {
                "file": str(model_path),
                "size_mb": file_size_mb(model_path),
                **evaluate_engine(float_engine, manifest.paths, manifest.labels),
            }
        }
    else:
        results = {"float": {"file": str(model_path), "size_mb": file_size_mb(model_path)}}

    # ---------------- TFLite dynamic-range ----------------
    stem = "mobilenetv2_cassava"
    dyn_path = out_dir / f"{stem}_dynamic.tflite"
    print("\n[convert] TFLite dynamic-range quantisation …")
    to_tflite(model_path, dyn_path, full_int8=False, calibration_paths=manifest.paths)
    artefacts.append(("tflite_dynamic", dyn_path))

    # ---------------- TFLite full-int8 (optional) ----------------
    if args.full_int8:
        cal_paths = manifest.paths
        if args.data_for_calibration:
            from cassava_dataset import load_manifest

            items, _ = load_manifest(Path(args.data_for_calibration))
            cal_paths = [p for p, _ in items]
        int8_path = out_dir / f"{stem}_int8.tflite"
        print(f"[convert] TFLite full-int8 ({len(cal_paths)} calibration images) …")
        try:
            to_tflite(model_path, int8_path, full_int8=True, calibration_paths=cal_paths)
            artefacts.append(("tflite_int8", int8_path))
        except Exception as exc:  # pragma: no cover - converter limits
            print(f"  skipped: {exc}")

    # ---------------- ONNX (optional) ----------------
    if args.onnx:
        onnx_path = out_dir / f"{stem}.onnx"
        print("[convert] ONNX …")
        if to_onnx(model_path, onnx_path):
            artefacts.append(("onnx", onnx_path))
        else:
            print("  skipped: tf2onnx/onnx not available (pip install tf2onnx onnx)")

    # ---------------- evaluate artefacts ----------------
    for name, path in artefacts:
        if args.no_eval:
            results[name] = {"file": str(path), "size_mb": file_size_mb(path)}
            continue
        print(f"[evaluate] {name} …")
        try:
            engine = InferenceEngine(path)
        except ModuleNotFoundError:
            print(f"  skipped: runtime for '{path.suffix}' not installed "
                  "(pip install onnxruntime)")
            results[name] = {"file": str(path), "size_mb": file_size_mb(path)}
            continue
        results[name] = {
            "file": str(path),
            "size_mb": file_size_mb(path),
            **evaluate_engine(engine, manifest.paths, manifest.labels),
        }

    # ---------------- comparison table ----------------
    baseline = results["float"]
    print("\n" + "=" * 78)
    print(f"{'artefact':<18}{'size MB':>10}{'Δ size':>10}{'acc':>9}{'F1':>9}{'latency ms':>12}")
    print("-" * 78)
    for name, r in results.items():
        size = r.get("size_mb", float("nan"))
        delta = (
            f"{(r['size_mb'] / baseline['size_mb'] - 1) * 100:+.1f}%"
            if name != "float" and "size_mb" in r
            else "—"
        )
        acc = f"{r['accuracy']:.4f}" if "accuracy" in r else "—"
        f1 = f"{r['f1_macro']:.4f}" if "f1_macro" in r else "—"
        lat = f"{r['latency_ms']:.1f}" if "latency_ms" in r else "—"
        print(f"{name:<18}{size:>10}{delta:>10}{acc:>9}{f1:>9}{lat:>12}")
    print("=" * 78)

    # accuracy/F1 drop vs float
    if "accuracy" in baseline:
        for name, r in results.items():
            if name != "float" and "accuracy" in r:
                d_acc = r["accuracy"] - baseline["accuracy"]
                d_f1 = r["f1_macro"] - baseline["f1_macro"]
                print(f"{name}: Δacc {d_acc:+.4f}, ΔF1 {d_f1:+.4f}")

    report_path = out_dir / "quantisation_report.json"
    save_json(report_path, results)
    print(f"\nReport written: {report_path}")

    # FastAPI hint
    best_tflite = next(
        (r["file"] for n, r in results.items() if n.startswith("tflite") and "file" in r),
        None,
    )
    if best_tflite:
        print(
            "\nFastAPI: set  MODEL_PATH="
            f"{best_tflite}\n"
            "  (TFLite needs `pip install tflite-runtime` or tensorflow; "
            "ONNX works with `pip install onnxruntime`)"
        )


if __name__ == "__main__":
    main()
