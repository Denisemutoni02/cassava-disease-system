"""Dataset loading, stratified splitting, augmentation and imbalance checks.

Supported layouts
-----------------
1. Flat class folders::

       data_root/
       ├── Healthy/*.jpg
       ├── CMD/*.jpg
       └── CBSD/*.jpg

2. Pre-split folders (used as-is; a test split is carved from ``val/`` if
   ``test/`` is missing)::

       data_root/
       ├── train/{Healthy,CMD,CBSD}/*
       ├── val/{Healthy,CMD,CBSD}*
       └── test/{Healthy,CMD,CBSD}*      # optional

3. CSV manifest with columns ``image_path,label`` (labels ∈ Healthy/CMD/CBSD).

All images are decoded, resized to 224×224, normalised to [-1, 1]
(MobileNetV2 convention). Training images additionally receive augmentation:
rotation, horizontal/vertical flip, brightness, contrast and slight zoom.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import tensorflow as tf

from common import CLASS_NAMES, IMG_SIZE, LABEL_TO_INDEX

VALID_LABELS = set(CLASS_NAMES)
IMG_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


# ---------------------------------------------------------------------------
# Manifest loading (folder / CSV → list of (path, label))
# ---------------------------------------------------------------------------


@dataclass
class Split:
    """Paths + integer labels for one split."""

    paths: list[str]
    labels: list[int]  # integer class indices

    def counts(self) -> dict[str, int]:
        c = Counter(self.labels)
        return {CLASS_NAMES[i]: c.get(i, 0) for i in range(len(CLASS_NAMES))}


def _label_from_dir(name: str) -> str | None:
    """Normalise a folder name to a canonical label (case-insensitive)."""
    key = name.strip().lower()
    for label in CLASS_NAMES:
        if key == label.lower():
            return label
    # common aliases
    aliases = {
        "cassava mosaic disease": "CMD",
        "cassava brown streak disease": "CBSD",
        "healthy leaf": "Healthy",
        "healthy_leaves": "Healthy",
        "cmd leaf": "CMD",
        "cbsd leaf": "CBSD",
    }
    return aliases.get(key)


def _scan_class_dir(class_dir: Path, label: str) -> list[tuple[str, str]]:
    items = []
    for p in sorted(class_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS:
            items.append((str(p), label))
    return items


def load_manifest_from_csv(csv_path: Path) -> list[tuple[str, str]]:
    """Read a CSV with columns: image_path,label."""
    items: list[tuple[str, str]] = []
    base = csv_path.parent
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"Empty CSV: {csv_path}")
        cols = {c.strip().lower(): c for c in reader.fieldnames}
        if "image_path" not in cols or "label" not in cols:
            raise ValueError(
                f"CSV must have columns 'image_path,label' — got {reader.fieldnames}"
            )
        for row in reader:
            raw_path = row[cols["image_path"]].strip()
            label = _label_from_dir(row[cols["label"]]) or row[cols["label"]].strip()
            if label not in VALID_LABELS:
                raise ValueError(
                    f"Invalid label '{label}' for {raw_path}. "
                    f"Allowed: {sorted(VALID_LABELS)}"
                )
            path = Path(raw_path)
            if not path.is_absolute():
                path = base / path
            items.append((str(path), label))
    if not items:
        raise ValueError(f"No rows found in {csv_path}")
    return items


def load_manifest(data_root: Path, csv: Path | None = None) -> tuple[list[tuple[str, str]], str]:
    """Return ([(path, label)], layout) where layout is csv|flat|presplit."""
    if csv is not None:
        return load_manifest_from_csv(csv), "csv"

    data_root = Path(data_root)
    if not data_root.is_dir():
        raise SystemExit(f"Data path not found: {data_root}")

    # Flat: class dirs directly under root
    flat_items: list[tuple[str, str]] = []
    found_class_dirs = []
    for d in sorted(p for p in data_root.iterdir() if p.is_dir()):
        label = _label_from_dir(d.name)
        if label:
            found_class_dirs.append(d)
            flat_items.extend(_scan_class_dir(d, label))
    if flat_items and not (data_root / "train").is_dir():
        print(f"[data] layout: flat  ({len(flat_items)} images under {data_root})")
        return flat_items, "flat"

    # Pre-split: train/ val/ test/
    if (data_root / "train").is_dir():
        print("[data] layout: pre-split (train/ [+val/] [+test/])")
        return [], "presplit"

    if flat_items:
        print(f"[data] layout: flat  ({len(flat_items)} images under {data_root})")
        return flat_items, "flat"

    raise SystemExit(
        f"No images found under {data_root}. Expected class folders "
        f"({', '.join(CLASS_NAMES)}), a train/ folder, or use --csv."
    )


def load_presplit(data_root: Path) -> tuple[Split, Split, Split]:
    """Load pre-split train/val/test folders.

    If ``test/`` is missing, a stratified half of ``val/`` is held out as the
    test set (deterministic, with a printed warning).
    """
    data_root = Path(data_root)

    def read_split(name: str) -> Split:
        root = data_root / name
        if not root.is_dir():
            return Split([], [])
        items: list[tuple[str, str]] = []
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            label = _label_from_dir(d.name)
            if label:
                items.extend(_scan_class_dir(d, label))
        # allow images sitting directly in split root too
        for p in sorted(root.iterdir()):
            if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS:
                raise SystemExit(
                    f"Loose images in {root} — organise them into class subfolders."
                )
        return _to_split(items)

    train, val, test = read_split("train"), read_split("val"), read_split("test")

    if not train.paths:
        raise SystemExit(f"Empty train split under {data_root / 'train'}")
    if not test.paths:
        if not val.paths:
            raise SystemExit(f"Need at least val/ or test/ under {data_root}")
        print(
            "[data] WARNING: no test/ folder — carving a stratified 50% of val/ "
            "as the test set (val will shrink accordingly)."
        )
        test = _stratified_holdout(val, fraction=0.5, seed=13)
        val = _remove_split(val, test)
    return train, val, test


# ---------------------------------------------------------------------------
# Stratified splitting
# ---------------------------------------------------------------------------


def _to_split(items: list[tuple[str, str]]) -> Split:
    return Split(
        paths=[p for p, _ in items],
        labels=[LABEL_TO_INDEX[l] for _, l in items],
    )


def stratified_split(
    items: list[tuple[str, str]],
    val_fraction: float,
    test_fraction: float,
    seed: int,
) -> tuple[Split, Split, Split]:
    """Shuffle per class, then slice each class by the same fractions."""
    if val_fraction + test_fraction >= 1.0:
        raise SystemExit("--val-split + --test-split must be < 1.0")

    by_class: dict[str, list[str]] = {k: [] for k in CLASS_NAMES}
    for path, label in items:
        by_class[label].append(path)

    import random as _random

    rng = _random.Random(seed)
    train_paths: list[str] = []
    val_paths: list[str] = []
    test_paths: list[str] = []

    for label in CLASS_NAMES:
        paths = list(by_class[label])
        rng.shuffle(paths)
        n = len(paths)
        if n < 10:
            raise SystemExit(
                f"Class '{label}' has only {n} images — need at least 10 to split."
            )
        n_test = max(1, int(round(n * test_fraction)))
        n_val = max(1, int(round(n * val_fraction)))
        n_train = n - n_test - n_val
        if n_train < 1:
            raise SystemExit(
                f"Split leaves 0 training images for '{label}' — reduce split fractions."
            )
        test_paths += paths[:n_test]
        val_paths += paths[n_test : n_test + n_val]
        train_paths += paths[n_test + n_val :]

    idx = LABEL_TO_INDEX
    train = Split(train_paths, [idx[_label_of(p, items)] for p in train_paths])
    val = Split(val_paths, [idx[_label_of(p, items)] for p in val_paths])
    test = Split(test_paths, [idx[_label_of(p, items)] for p in test_paths])
    return train, val, test


def _label_of(path: str, items: list[tuple[str, str]]) -> str:
    for p, label in items:
        if p == path:
            return label
    raise KeyError(path)


def _stratified_holdout(split: Split, fraction: float, seed: int) -> Split:
    """Take a stratified `fraction` of each class out of `split`."""
    import random as _random

    rng = _random.Random(seed)
    by_class: dict[int, list[str]] = {}
    for path, label in zip(split.paths, split.labels):
        by_class.setdefault(label, []).append(path)

    held: list[str] = []
    for label, paths in by_class.items():
        rng.shuffle(paths)
        k = max(1, int(round(len(paths) * fraction)))
        held += paths[:k]
    held_set = set(held)
    labels_of = dict(zip(split.paths, split.labels))
    return Split(sorted(held_set), [labels_of[p] for p in sorted(held_set)])


def _remove_split(base: Split, taken: Split) -> Split:
    taken_set = set(taken.paths)
    keep = [(p, l) for p, l in zip(base.paths, base.labels) if p not in taken_set]
    return Split([p for p, _ in keep], [l for _, l in keep])


# ---------------------------------------------------------------------------
# Class distribution + imbalance warning
# ---------------------------------------------------------------------------


def report_distribution(train: Split, val: Split, test: Split) -> dict:
    """Print class counts for every split; warn when classes are imbalanced."""
    dist = {
        "train": train.counts(),
        "val": val.counts(),
        "test": test.counts(),
    }
    print("\n[class distribution]")
    header = f"{'class':<10}" + "".join(f"{s:>10}" for s in dist)
    print(header)
    for label in CLASS_NAMES:
        row = f"{label:<10}" + "".join(f"{dist[s][label]:>10}" for s in dist)
        print(row)

    counts = [dist["train"][l] for l in CLASS_NAMES]
    total = sum(counts)
    majority, minority = max(counts), min(counts)
    ratio = majority / max(minority, 1)
    minority_share = minority / max(total, 1)

    imbalance = False
    if ratio >= 2.0 or minority_share < 0.15:
        imbalance = True
        print(
            "\n[class imbalance] WARNING: training classes are heavily imbalanced "
            f"(majority:minority = {ratio:.1f}:1, minority share "
            f"{minority_share:.0%}).\n"
            "  → Balanced sample weights will be applied automatically.\n"
            "  → Prefer collecting more minority-class images for best results."
        )
    elif ratio >= 1.5:
        print(
            f"\n[class imbalance] NOTE: mild imbalance detected "
            f"({ratio:.1f}:1). Balanced sample weights will be applied."
        )
        imbalance = True
    else:
        print("\n[class imbalance] OK: classes are reasonably balanced.")
    dist["imbalance"] = imbalance
    dist["train_majority_minority_ratio"] = round(ratio, 2)
    return dist


def balanced_sample_weights(labels: list[int]) -> list[float]:
    """Per-sample weights inversely proportional to class frequency."""
    counts = Counter(labels)
    n = len(labels)
    k = len(counts)
    weights = {c: n / (k * cnt) for c, cnt in counts.items()}
    return [weights[l] for l in labels]


# ---------------------------------------------------------------------------
# tf.data pipelines
# ---------------------------------------------------------------------------


def _decode(path: str, label: int) -> tuple[tf.Tensor, tf.Tensor]:
    img = tf.io.read_file(path)
    # decode_image handles jpeg/png/gif/bmp; expand_animations=False keeps 3-D
    img = tf.image.decode_image(img, channels=3, expand_animations=False)
    img.set_shape([None, None, 3])
    img = tf.image.resize(img, IMG_SIZE, method="bilinear")
    img = tf.cast(img, tf.float32) / 127.5 - 1.0  # MobileNetV2 preprocessing
    return img, tf.one_hot(label, depth=len(CLASS_NAMES))


def _decode_weighted(path: str, label: int, weight: float) -> tuple[tf.Tensor, tf.Tensor, tf.Tensor]:
    """Same as _decode but carries the per-sample weight through the pipeline.

    Keras 3 refuses ``sample_weight=`` alongside a tf.data.Dataset, so balanced
    class weights must travel inside the dataset as a third tensor.
    """
    img, y = _decode(path, label)
    return img, y, tf.cast(weight, tf.float32)


def make_augmentation(seed: int | None = None) -> tf.keras.Sequential:
    """Rotation · flips · brightness · contrast · zoom (train only)."""
    return tf.keras.Sequential(
        [
            tf.keras.layers.RandomFlip("horizontal_and_vertical", seed=seed),
            tf.keras.layers.RandomRotation(0.08, seed=seed),        # ±~29°
            tf.keras.layers.RandomZoom(0.1, seed=seed),             # up to 10%
            tf.keras.layers.RandomBrightness(0.15, seed=seed),
            tf.keras.layers.RandomContrast(0.15, seed=seed),
        ],
        name="augmentation",
    )


def build_datasets(
    train: Split,
    val: Split,
    test: Split,
    batch_size: int,
    seed: int,
    augment: bool = True,
    sample_weights: list[float] | None = None,
) -> tuple[tf.data.Dataset, tf.data.Dataset, tf.data.Dataset]:
    """Build batched, shuffled, (optionally augmented) train/val/test datasets.

    ``sample_weights`` (aligned with ``train.paths``) are embedded into the
    training dataset as a third tensor — required by Keras 3, which does not
    accept ``sample_weight=`` next to a tf.data.Dataset.
    """

    def pipeline(
        split: Split,
        training: bool,
        weights: list[float] | None = None,
    ) -> tf.data.Dataset:
        if weights is not None:
            ds = tf.data.Dataset.from_tensor_slices(
                (split.paths, split.labels, weights)
            )
            decode = _decode_weighted
        else:
            ds = tf.data.Dataset.from_tensor_slices((split.paths, split.labels))
            decode = _decode

        if training:
            ds = ds.shuffle(len(split.paths), seed=seed, reshuffle_each_iteration=True)
        ds = ds.map(decode, num_parallel_calls=tf.data.AUTOTUNE)

        if training and augment:
            aug = make_augmentation(seed=seed)
            if weights is not None:
                ds = ds.map(
                    lambda x, y, w: (aug(x, training=True), y, w),
                    num_parallel_calls=tf.data.AUTOTUNE,
                )
            else:
                ds = ds.map(
                    lambda x, y: (aug(x, training=True), y),
                    num_parallel_calls=tf.data.AUTOTUNE,
                )

        return ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)

    return (
        pipeline(train, True, sample_weights),
        pipeline(val, False),
        pipeline(test, False),
    )


def write_manifest(path: Path, split: Split) -> None:
    """Persist a split as CSV (image_path,label) so evaluation is repeatable.

    Paths are written absolute so the manifest can be read from any CWD
    (e.g. by quantise.py running later).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["image_path", "label"])
        for p, l in zip(split.paths, split.labels):
            writer.writerow([str(Path(p).resolve()), CLASS_NAMES[l]])


def read_manifest(path: Path) -> Split:
    items = load_manifest_from_csv(path)
    return _to_split(items)
