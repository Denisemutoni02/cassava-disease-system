"""Fine-tune MobileNetV2 (ImageNet weights) on cassava leaf images.

Classes (folder names): Healthy, CMD, CBSD — always exported in alphabetical
order so the backend class-index mapping stays in sync.

Two-phase transfer learning:
  1. Freeze the MobileNetV2 backbone, train the softmax head.
  2. Unfreeze the top ~30% of the backbone and fine-tune at a low LR
     (weights from phase 1 are kept — the same model object is reused).

Usage:
    python train.py --data-dir ../data/synthetic --epochs 3 --fine-tune-epochs 2
    python train.py --data-dir /path/to/kaggle-cassava --epochs 15 --fine-tune-epochs 5

Output: models/mobilenetv2_cassava.keras (+ metrics.json)
Then quantise:  python export_tflite.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import tensorflow as tf

CLASS_NAMES = ["CBSD", "CMD", "Healthy"]  # alphabetical — must match backend
IMG_SIZE = (224, 224)


def build_datasets(data_dir: Path, batch_size: int):
    train_dir = data_dir / "train"
    val_dir = data_dir / "val"
    if not train_dir.is_dir():
        raise SystemExit(f"Missing {train_dir}. Run generate_synthetic_dataset.py first.")

    train_ds = tf.keras.utils.image_dataset_from_directory(
        train_dir,
        labels="inferred",
        label_mode="categorical",
        class_names=CLASS_NAMES,
        image_size=IMG_SIZE,
        batch_size=batch_size,
        shuffle=True,
        seed=42,
    )
    val_ds = tf.keras.utils.image_dataset_from_directory(
        val_dir,
        labels="inferred",
        label_mode="categorical",
        class_names=CLASS_NAMES,
        image_size=IMG_SIZE,
        batch_size=batch_size,
        shuffle=False,
    )

    # MobileNetV2 preprocessing: scale pixels to [-1, 1]
    norm = tf.keras.layers.Rescaling(1.0 / 127.5, offset=-1)
    autotune = tf.data.AUTOTUNE
    train_ds = train_ds.map(lambda x, y: (norm(x), y), num_parallel_calls=autotune).prefetch(autotune)
    val_ds = val_ds.map(lambda x, y: (norm(x), y), num_parallel_calls=autotune).prefetch(autotune)
    return train_ds, val_ds


def build_model(num_classes: int) -> tuple[tf.keras.Model, tf.keras.Model]:
    """Return (full model, backbone). Backbone starts frozen."""
    base = tf.keras.applications.MobileNetV2(
        input_shape=(*IMG_SIZE, 3),
        include_top=False,
        weights="imagenet",
    )
    base.trainable = False

    inputs = tf.keras.Input(shape=(*IMG_SIZE, 3))
    x = base(inputs, training=False)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dropout(0.2)(x)
    outputs = tf.keras.layers.Dense(num_classes, activation="softmax")(x)
    model = tf.keras.Model(inputs, outputs, name="cassava_mobilenetv2")
    return model, base


def unfreeze_for_fine_tune(base: tf.keras.Model, fine_tune_at: int) -> None:
    """Unfreeze base layers from index `fine_tune_at`; keep BatchNorm frozen."""
    base.trainable = True
    for layer in base.layers[:fine_tune_at]:
        layer.trainable = False
    for layer in base.layers:
        if isinstance(layer, tf.keras.layers.BatchNormalization):
            layer.trainable = False
    trainable = sum(int(l.trainable) for l in base.layers)
    print(f"Fine-tune: {trainable}/{len(base.layers)} backbone layers trainable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="../data/synthetic")
    parser.add_argument("--epochs", type=int, default=5, help="Head-training epochs")
    parser.add_argument("--fine-tune-epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--fine-tune-lr", type=float, default=1e-5)
    parser.add_argument(
        "--fine-tune-at",
        type=int,
        default=100,
        help="Backbone layer index where fine-tuning starts (≈ last 30%% of MobileNetV2)",
    )
    parser.add_argument("--out", default="models/mobilenetv2_cassava.keras")
    args = parser.parse_args()

    print(f"TensorFlow {tf.__version__}")
    train_ds, val_ds = build_datasets(Path(args.data_dir).resolve(), args.batch_size)

    # ---------------- Phase 1: head only ----------------
    model, base = build_model(len(CLASS_NAMES))
    model.compile(
        optimizer=tf.keras.optimizers.Adam(args.lr),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    model.summary()
    print("\n=== Phase 1: training classification head ===")
    h1 = model.fit(train_ds, validation_data=val_ds, epochs=args.epochs)
    history = {"head": h1.history}

    # ---------------- Phase 2: fine-tune backbone (same model) ----------------
    if args.fine_tune_epochs > 0:
        print("\n=== Phase 2: fine-tuning top of MobileNetV2 ===")
        unfreeze_for_fine_tune(base, args.fine_tune_at)
        model.compile(
            optimizer=tf.keras.optimizers.Adam(args.fine_tune_lr),
            loss="categorical_crossentropy",
            metrics=["accuracy"],
        )
        h2 = model.fit(train_ds, validation_data=val_ds, epochs=args.fine_tune_epochs)
        history["fine_tune"] = h2.history

    # ---------------- Evaluate + save ----------------
    loss, acc = model.evaluate(val_ds, verbose=0)
    print(f"\nValidation accuracy: {acc:.4f}  loss: {loss:.4f}")

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(out_path)
    metrics = {
        "val_accuracy": float(acc),
        "val_loss": float(loss),
        "class_names": CLASS_NAMES,
        "input_size": list(IMG_SIZE),
        "history": {
            k: {m: [float(x) for x in v] for m, v in h.items()} for k, h in history.items()
        },
    }
    (out_path.parent / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"Saved model  → {out_path}")
    print(f"Saved metrics→ {out_path.parent / 'metrics.json'}")
    print("Next: python export_tflite.py --model", out_path)


if __name__ == "__main__":
    main()
