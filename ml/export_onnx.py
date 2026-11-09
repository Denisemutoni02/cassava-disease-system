"""Export the trained Keras model to ONNX (fallback runtime for the backend).

Usage:
    python export_onnx.py --model models/mobilenetv2_cassava.keras
Requires:  pip install tf2onnx onnx
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="models/mobilenetv2_cassava.keras")
    parser.add_argument("--out", default="models/mobilenetv2_cassava.onnx")
    args = parser.parse_args()

    model_path = Path(args.model).resolve()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # tf2onnx works from a SavedModel; convert .keras → temp SavedModel first
    import tensorflow as tf

    model = tf.keras.models.load_model(model_path)
    saved_dir = out_path.parent / "_saved_model_tmp"
    # Keras 3: model.export() writes a TF SavedModel (model.save() only does .keras/.h5)
    model.export(saved_dir)

    cmd = [
        sys.executable, "-m", "tf2onnx.convert",
        "--saved-model", str(saved_dir),
        "--output", str(out_path),
        "--opset", "13",
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"ONNX model → {out_path} ({out_path.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
