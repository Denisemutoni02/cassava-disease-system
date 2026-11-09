"""Post-training quantisation: Keras model → TFLite.

Default mode is *dynamic-range quantisation* (weights → int8, activations
float) which shrinks MobileNetV2 from ~14 MB to ~3–4 MB with a tiny accuracy
cost — ideal for a Uganda-deployed server. ``--full-int8`` additionally
quantises activations using a representative dataset (requires calibration
images).

Usage:
    python export_tflite.py --model models/mobilenetv2_cassava.keras
    python export_tflite.py --full-int8 --data-dir ../data/synthetic/val
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import tensorflow as tf


def make_representative_dataset(data_dir: Path, count: int = 100):
    """Yield calibration batches in [-1, 1] (MobileNetV2 preprocessing)."""

    def gen():
        seen = 0
        for path in sorted(data_dir.rglob("*.jpg")):
            img = tf.keras.utils.load_img(path, target_size=(224, 224))
            arr = tf.keras.utils.img_to_array(img)
            arr = (arr / 127.5) - 1.0
            yield [arr.astype(np.float32)]
            seen += 1
            if seen >= count:
                return

    return gen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="models/mobilenetv2_cassava.keras")
    parser.add_argument("--out", default="models/mobilenetv2_cassava.tflite")
    parser.add_argument(
        "--full-int8",
        action="store_true",
        help="Full-integer quantisation (needs --data-dir calibration images)",
    )
    parser.add_argument("--data-dir", default="../data/synthetic/val")
    args = parser.parse_args()

    model = tf.keras.models.load_model(args.model)
    converter = tf.lite.TFLiteConverter.from_keras_model(model)

    if args.full_int8:
        print("Mode: full-integer (int8) post-training quantisation")
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        data_dir = Path(args.data_dir).resolve()
        converter.representative_dataset = make_representative_dataset(data_dir)
        converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        converter.inference_input_type = tf.uint8
        converter.inference_output_type = tf.uint8
    else:
        print("Mode: dynamic-range quantisation (int8 weights, float activations)")
        converter.optimizations = [tf.lite.Optimize.DEFAULT]

    tflite_model = converter.convert()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(tflite_model)

    ksize = Path(args.model).stat().st_size / 1e6
    qsize = len(tflite_model) / 1e6
    print(f"Original : {ksize:.2f} MB  ({args.model})")
    print(f"Quantised: {qsize:.2f} MB  ({out_path})  →  shrink {100 * (1 - qsize / ksize):.0f}%")
    print("Point the backend MODEL_PATH at this file.")


if __name__ == "__main__":
    main()
