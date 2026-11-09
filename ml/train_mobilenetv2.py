"""Train a 3-class MobileNetV2 cassava-leaf classifier (transfer learning).

Two-phase training
------------------
1. Freeze the ImageNet backbone → train only the new softmax head (Adam, LR 1e-3).
2. Unfreeze the deeper part of the backbone → fine-tune with a low LR (1e-5).

The best checkpoint (highest validation macro-F1) is kept; early stopping
halts when the metric stalls. Reproducible via --seed.

Outputs (under --output-dir)
----------------------------
    best_model.keras          best full-precision model (by val macro-F1)
    run_config.json           arguments + seed for reproducibility
    history.json              per-epoch metrics
    training_curves.png       loss / accuracy / F1 curves
    classification_report.txt macro + per-class P/R/F1 on the TEST set
    classification_report.json machine-readable report
    confusion_matrix.png      test-set confusion matrix
    metrics.json              headline test metrics
    train_manifest.csv        exact split used (reused by quantise.py)

Usage
-----
    python train_mobilenetv2.py --data ../data/synthetic --output-dir models/run
    python train_mobilenetv2.py --data /path/to/flat_or_presplit --epochs 15 --fine-tune-epochs 5
    python train_mobilenetv2.py --csv mydataset.csv --batch-size 32
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import tensorflow as tf

from cassava_dataset import (
    balanced_sample_weights,
    build_datasets,
    load_manifest,
    load_presplit,
    report_distribution,
    stratified_split,
    write_manifest,
)
from common import CLASS_NAMES, IMG_SIZE, RECOMMENDED, save_json, set_seed

# Keep matplotlib non-interactive (servers have no display)
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--data", default="../data/synthetic",
                   help="Dataset root (flat class folders or train/val/test tree)")
    p.add_argument("--csv", default=None,
                   help="CSV manifest with columns image_path,label (overrides --data layout)")
    p.add_argument("--output-dir", default="models/run",
                   help="Where checkpoints, plots and reports are written")
    p.add_argument("--epochs", type=int, default=RECOMMENDED["epochs"],
                   help="Phase-1 epochs (head only)")
    p.add_argument("--fine-tune-epochs", type=int, default=RECOMMENDED["fine_tune_epochs"],
                   help="Phase-2 epochs (backbone fine-tuning); 0 disables phase 2")
    p.add_argument("--batch-size", type=int, default=RECOMMENDED["batch_size"])
    p.add_argument("--lr", type=float, default=RECOMMENDED["lr"],
                   help="Phase-1 learning rate")
    p.add_argument("--fine-tune-lr", type=float, default=RECOMMENDED["fine_tune_lr"],
                   help="Phase-2 learning rate")
    p.add_argument("--fine-tune-at", type=int, default=RECOMMENDED["fine_tune_at"],
                   help="Backbone layer index where fine-tuning starts")
    p.add_argument("--patience", type=int, default=RECOMMENDED["patience"],
                   help="Early-stopping patience (epochs)")
    p.add_argument("--val-split", type=float, default=RECOMMENDED["val_split"],
                   help="Validation fraction (flat/CSV layouts only)")
    p.add_argument("--test-split", type=float, default=RECOMMENDED["test_split"],
                   help="Test fraction (flat/CSV layouts only)")
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    p.add_argument("--no-augment", action="store_true", help="Disable data augmentation")
    p.add_argument("--weights", default=None,
                   help="Optional starting weights (e.g. a previous best_model.keras)")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def macro_f1(y_true_onehot: np.ndarray, y_pred_idx: np.ndarray) -> float:
    from sklearn.metrics import f1_score

    y_true = y_true_onehot.argmax(axis=1)
    return float(f1_score(y_true, y_pred_idx, average="macro", zero_division=0))


class ValF1Callback(tf.keras.callbacks.Callback):
    """Computes validation macro-F1 after every epoch and injects it into
    logs as ``val_macro_f1`` so EarlyStopping/ModelCheckpoint can monitor it.

    Must be listed FIRST in callbacks so downstream callbacks see the value.
    """

    def __init__(self, val_dataset: tf.data.Dataset):
        super().__init__()
        self.val_dataset = val_dataset
        self.history: list[float] = []

    def on_epoch_end(self, epoch, logs=None):
        logs = logs or {}
        ys, preds = [], []
        for x, y in self.val_dataset:
            probs = self.model.predict(x, verbose=0)
            ys.append(y.numpy())
            preds.append(probs.argmax(axis=1))
        y_true = np.concatenate(ys)
        y_pred = np.concatenate(preds)
        f1 = macro_f1(y_true, y_pred)
        logs["val_macro_f1"] = f1
        self.history.append(f1)
        print(f" — val_macro_f1: {f1:.4f}", end="")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def build_model(frozen: bool, fine_tune_at: int | None = None) -> tuple[tf.keras.Model, tf.keras.Model]:
    """Return (full model, backbone)."""
    base = tf.keras.applications.MobileNetV2(
        input_shape=(*IMG_SIZE, 3),
        include_top=False,
        weights="imagenet",
    )
    base.trainable = not frozen

    inputs = tf.keras.Input(shape=(*IMG_SIZE, 3))
    x = base(inputs, training=False)          # BN in inference mode while frozen
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dropout(0.2)(x)
    outputs = tf.keras.layers.Dense(len(CLASS_NAMES), activation="softmax", name="head")(x)
    model = tf.keras.Model(inputs, outputs, name="cassava_mobilenetv2")

    if fine_tune_at is not None:
        base.trainable = True
        for layer in base.layers[:fine_tune_at]:
            layer.trainable = False
        for layer in base.layers:
            if isinstance(layer, tf.keras.layers.BatchNormalization):
                layer.trainable = False
    return model, base


# ---------------------------------------------------------------------------
# Plots & reports
# ---------------------------------------------------------------------------


def plot_curves(history: dict, val_f1: list[float], out: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.2))
    epochs = range(1, len(history["loss"]) + 1)

    axes[0].plot(epochs, history["loss"], label="train")
    axes[0].plot(epochs, history["val_loss"], label="val")
    axes[0].set_title("Loss"); axes[0].set_xlabel("epoch"); axes[0].legend()

    axes[1].plot(epochs, history["accuracy"], label="train")
    axes[1].plot(epochs, history["val_accuracy"], label="val")
    axes[1].set_title("Accuracy"); axes[1].set_xlabel("epoch"); axes[1].legend()

    axes[2].plot(epochs, history.get("accuracy", [])[: len(val_f1)], "--", label="train acc")
    axes[2].plot(epochs, val_f1, label="val macro-F1")
    axes[2].set_title("Validation macro-F1"); axes[2].set_xlabel("epoch"); axes[2].legend()

    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def evaluate_on_test(model: tf.keras.Model, test_ds: tf.data.Dataset, out_dir: Path) -> dict:
    """Classification report + confusion matrix on the held-out test set."""
    from sklearn.metrics import (
        classification_report,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
    )

    ys, preds, probs_all = [], [], []
    for x, y in test_ds:
        probs = model.predict(x, verbose=0)
        ys.append(y.numpy())
        preds.append(probs.argmax(axis=1))
        probs_all.append(probs)
    y_true = np.concatenate(ys).argmax(axis=1)
    y_pred = np.concatenate(preds)
    y_prob = np.concatenate(probs_all)

    report_str = classification_report(
        y_true, y_pred, target_names=CLASS_NAMES, digits=4, zero_division=0
    )
    report_dict = classification_report(
        y_true, y_pred, target_names=CLASS_NAMES, output_dict=True, zero_division=0
    )
    cm = confusion_matrix(y_true, y_pred, labels=list(range(len(CLASS_NAMES))))

    metrics = {
        "test_accuracy": float((y_true == y_pred).mean()),
        "test_precision_macro": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "test_recall_macro": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "test_f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "n_test_images": int(len(y_true)),
    }

    (out_dir / "classification_report.txt").write_text(
        f"Test-set classification report ({len(y_true)} images)\n"
        + "=" * 60 + "\n" + report_str,
        encoding="utf-8",
    )
    save_json(out_dir / "classification_report.json", report_dict)
    save_json(out_dir / "metrics.json", metrics)

    # Confusion matrix figure
    fig, ax = plt.subplots(figsize=(5.2, 4.6))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(CLASS_NAMES)), CLASS_NAMES, rotation=30, ha="right")
    ax.set_yticks(range(len(CLASS_NAMES)), CLASS_NAMES)
    ax.set_xlabel("Predicted"); ax.set_ylabel("True")
    ax.set_title("Confusion matrix (test)")
    for i in range(len(CLASS_NAMES)):
        for j in range(len(CLASS_NAMES)):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() / 2 else "black")
    fig.colorbar(im, fraction=0.046)
    fig.tight_layout()
    fig.savefig(out_dir / "confusion_matrix.png", dpi=120)
    plt.close(fig)

    print("\n===== TEST SET =====")
    print(report_str)
    print(
        f"accuracy={metrics['test_accuracy']:.4f}  "
        f"macro-F1={metrics['test_f1_macro']:.4f}"
    )
    return metrics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---------------- 1. Load & split ----------------
    csv_path = Path(args.csv) if args.csv else None
    items, layout = load_manifest(Path(args.data), csv_path)

    if layout == "presplit":
        from cassava_dataset import Split  # noqa: F401  (documentation)

        train, val, test = load_presplit(Path(args.data))
    else:
        train, val, test = stratified_split(
            items,
            val_fraction=args.val_split,
            test_fraction=args.test_split,
            seed=args.seed,
        )

    distribution = report_distribution(train, val, test)
    sample_weights = (
        balanced_sample_weights(train.labels)
        if distribution.get("imbalance")
        else None
    )

    # Persist the exact split for reproducible downstream evaluation
    write_manifest(out_dir / "train_manifest.csv", train)
    write_manifest(out_dir / "val_manifest.csv", val)
    write_manifest(out_dir / "test_manifest.csv", test)

    train_ds, val_ds, test_ds = build_datasets(
        train, val, test,
        batch_size=args.batch_size,
        seed=args.seed,
        augment=not args.no_augment,
        sample_weights=sample_weights,
    )

    save_json(
        out_dir / "run_config.json",
        {**vars(args), "class_names": CLASS_NAMES, "layout": layout,
         "train_size": len(train.paths), "val_size": len(val.paths),
         "test_size": len(test.paths)},
    )

    # ---------------- 2. Phase 1 — head ----------------
    print("\n=== Phase 1: training head (backbone frozen) ===")
    model, base = build_model(frozen=True)
    if args.weights:
        model.load_weights(args.weights)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(args.lr),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    model.summary()

    f1_cb = ValF1Callback(val_ds)
    callbacks = [
        f1_cb,  # FIRST: injects val_macro_f1 for the callbacks below
        tf.keras.callbacks.EarlyStopping(
            monitor="val_macro_f1", patience=args.patience,
            mode="max", restore_best_weights=True,
        ),
        tf.keras.callbacks.ModelCheckpoint(
            filepath=str(out_dir / "best_model.keras"),
            monitor="val_macro_f1", mode="max",
            save_best_only=True, verbose=1,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=max(2, args.patience // 2),
            min_lr=1e-6, verbose=1,
        ),
    ]

    h1 = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=args.epochs,
        callbacks=callbacks,
        verbose=2,
    )
    history = {k: [float(v) for v in vals] for k, vals in h1.history.items()}
    # Keras stores callback logs under plain keys too; ensure f1 list present
    val_f1_history = list(f1_cb.history)

    # ---------------- 3. Phase 2 — fine-tune ----------------
    if args.fine_tune_epochs > 0:
        print("\n=== Phase 2: fine-tuning deeper backbone layers ===")
        # Unfreeze on the SAME model so phase-1 weights are preserved
        base.trainable = True
        for layer in base.layers[: args.fine_tune_at]:
            layer.trainable = False
        for layer in base.layers:
            if isinstance(layer, tf.keras.layers.BatchNormalization):
                layer.trainable = False
        trainable = sum(int(l.trainable) for l in base.layers)
        print(f"trainable backbone layers: {trainable}/{len(base.layers)}")

        model.compile(
            optimizer=tf.keras.optimizers.Adam(args.fine_tune_lr),
            loss="categorical_crossentropy",
            metrics=["accuracy"],
        )
        h2 = model.fit(
            train_ds,
            validation_data=val_ds,
            epochs=args.fine_tune_epochs,
            callbacks=callbacks,   # same checkpoint/early-stop on macro-F1
            verbose=2,
        )
        for k, vals in h2.history.items():
            history.setdefault(k, []).extend(float(v) for v in vals)
        val_f1_history.extend(f1_cb.history[len(val_f1_history):])

    # Keep the best-checkpoint weights in memory for final evaluation
    best_path = out_dir / "best_model.keras"
    if best_path.exists():
        model.load_weights(best_path)

    # ---------------- 4. Save history + curves ----------------
    save_json(out_dir / "history.json", {**history, "val_macro_f1": val_f1_history})
    plot_curves(history, val_f1_history, out_dir / "training_curves.png")
    print(f"\nSaved: {best_path}")
    print(f"Saved: {out_dir / 'history.json'}")
    print(f"Saved: {out_dir / 'training_curves.png'}")

    # ---------------- 5. Test evaluation ----------------
    test_metrics = evaluate_on_test(model, test_ds, out_dir)

    # Re-save best model ensuring it's the checkpointed one
    model.save(best_path)

    print("\nDone. Next steps:")
    print(f"  python quantise.py --model {best_path} "
          f"--test-manifest {out_dir / 'test_manifest.csv'}")
    print(f"  python predict.py --model <quantised-model> --image <leaf.jpg>")


if __name__ == "__main__":
    main()
