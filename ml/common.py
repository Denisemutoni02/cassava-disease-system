"""Shared constants and helpers for the cassava ML pipeline.

Kept dependency-free (no TensorFlow import) so scripts can share label
mappings without pulling in the heavy runtime.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

# Windows consoles default to cp1252 when stdout/stderr are redirected to a
# file, which crashes on characters like "→" or "Δ". Force UTF-8 everywhere so
# logs are safe to redirect (`python train_mobilenetv2.py > run.log`).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover - exotic stream wrappers
            pass

# Fixed class order — MUST match backend/app/services/classifier.py.
# Alphabetical so exports are deterministic.
CLASS_NAMES: list[str] = ["CBSD", "CMD", "Healthy"]
LABEL_TO_INDEX: dict[str, int] = {name: i for i, name in enumerate(CLASS_NAMES)}

# MobileNetV2 input geometry
IMG_SIZE: tuple[int, int] = (224, 224)

# Recommended first-run hyperparameters (documented in README)
RECOMMENDED = {
    "epochs": 10,
    "fine_tune_epochs": 5,
    "batch_size": 32,
    "lr": 1e-3,
    "fine_tune_lr": 1e-5,
    "fine_tune_at": 100,
    "patience": 4,
    "val_split": 0.15,
    "test_split": 0.15,
}


def set_seed(seed: int) -> None:
    """Seed Python, NumPy and TensorFlow for reproducible runs."""
    import os

    import numpy as np

    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    try:
        import tensorflow as tf

        tf.random.set_seed(seed)
    except Exception:  # pragma: no cover - TF always present in ml env
        pass


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=float), encoding="utf-8")


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
