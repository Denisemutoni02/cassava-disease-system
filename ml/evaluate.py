"""Quick evaluation of a saved model against a validation folder.

Usage:
    python evaluate.py --model models/mobilenetv2_cassava.keras --data-dir ../data/synthetic/val
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import tensorflow as tf

CLASS_NAMES = ["CBSD", "CMD", "Healthy"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="models/mobilenetv2_cassava.keras")
    parser.add_argument("--data-dir", default="../data/synthetic/val")
    args = parser.parse_args()

    model = tf.keras.models.load_model(args.model)
    data_dir = Path(args.data_dir).resolve()

    y_true, y_pred, confidences = [], [], []
    for idx, cls in enumerate(CLASS_NAMES):
        for path in sorted((data_dir / cls).glob("*.jpg")):
            img = tf.keras.utils.load_img(path, target_size=(224, 224))
            arr = tf.keras.utils.img_to_array(img)
            arr = ((arr / 127.5) - 1.0)[None, ...]
            probs = model.predict(arr, verbose=0)[0]
            y_true.append(idx)
            y_pred.append(int(np.argmax(probs)))
            confidences.append(float(np.max(probs)))

    y_true = np.array(y_true)
    y_pred = np.array(y_pred)
    acc = (y_true == y_pred).mean()
    print(f"Images evaluated : {len(y_true)}")
    print(f"Overall accuracy : {acc:.4f}")
    print(f"Mean confidence  : {np.mean(confidences):.4f}")
    print("\nPer-class recall:")
    for idx, cls in enumerate(CLASS_NAMES):
        mask = y_true == idx
        if mask.any():
            print(f"  {cls:8s} {(y_pred[mask] == idx).mean():.3f}  (n={mask.sum()})")
    print("\nConfusion matrix (rows=true, cols=pred):")
    cm = np.zeros((3, 3), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1
    print("         " + "  ".join(f"{c:>7s}" for c in CLASS_NAMES))
    for i, cls in enumerate(CLASS_NAMES):
        print(f"{cls:>8s} " + "  ".join(f"{cm[i, j]:7d}" for j in range(3)))


if __name__ == "__main__":
    main()
