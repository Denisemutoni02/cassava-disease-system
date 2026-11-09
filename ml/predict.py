"""Single-image prediction utility.

Loads a trained model (.keras / .tflite / .onnx), runs it on one leaf photo
and prints a JSON result:

    {
      "label": "CMD",
      "confidence": 0.93,
      "all_probabilities": {"Healthy": 0.02, "CMD": 0.93, "CBSD": 0.05}
    }

Usage
-----
    python predict.py --image ../data/samples/cmd_leaf.jpg
    python predict.py --image leaf.jpg --model models/mobilenetv2_cassava_dynamic.tflite
    python predict.py --image leaf.jpg --model models/run/best_model.keras --pretty
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import CLASS_NAMES
from inference import InferenceEngine

DEFAULT_MODEL = Path("models/mobilenetv2_cassava_dynamic.tflite")


def find_default_model() -> Path | None:
    """Best-effort model discovery when --model is omitted."""
    candidates = [
        DEFAULT_MODEL,
        Path("models/mobilenetv2_cassava.tflite"),
        Path("models/mobilenetv2_cassava.onnx"),
        Path("models/run/best_model.keras"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--image", required=True, help="Path to a leaf photo")
    parser.add_argument("--model", default=None,
                        help="Model file (.tflite/.onnx/.keras). "
                             "Auto-detected from common locations if omitted.")
    parser.add_argument("--pretty", action="store_true", help="Indent the JSON output")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        sys.exit(f"Image not found: {image_path}")

    model_path = Path(args.model) if args.model else find_default_model()
    if model_path is None:
        sys.exit(
            "No model file found. Pass --model explicitly, e.g.\n"
            "  python train_mobilenetv2.py --data <dataset>   # creates models/run/best_model.keras\n"
            "  python quantise.py                             # creates models/*_dynamic.tflite"
        )

    engine = InferenceEngine(model_path)
    result = engine.predict(image_path)
    result["model"] = str(model_path)
    result["model_kind"] = engine.kind
    result["classes"] = CLASS_NAMES

    # Keep the documented key order first
    ordered = {
        "label": result["label"],
        "confidence": result["confidence"],
        "all_probabilities": result["all_probabilities"],
        "model": result["model"],
        "model_kind": result["model_kind"],
    }
    print(json.dumps(ordered, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
