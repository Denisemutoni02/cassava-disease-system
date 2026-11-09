"""Model-loading + inference helpers shared by predict.py and quantise.py.

Supports three artefact types:
  • ``.keras``  – full-precision Keras model
  • ``.tflite`` – quantised TFLite model (dynamic-range or full-int8)
  • ``.onnx``   – ONNX export (easy to load from FastAPI via onnxruntime)

All paths normalise inputs exactly like training: resize 224×224, scale to
[-1, 1].
"""

from __future__ import annotations

import os
import time
from pathlib import Path

# Keep stdout clean for JSON output (TF C++ logs go to stderr)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np
from PIL import Image

from common import CLASS_NAMES, IMG_SIZE


def preprocess(image_path: str | Path) -> np.ndarray:
    """Image file → float32 batch (1, 224, 224, 3) in [-1, 1]."""
    img = Image.open(image_path).convert("RGB").resize(IMG_SIZE, Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32)
    arr = arr / 127.5 - 1.0
    return arr[None, ...]


def _ensure_probs(x: np.ndarray) -> np.ndarray:
    """Accept either logits or softmax probabilities; return probabilities."""
    x = np.asarray(x, dtype=np.float64).reshape(-1)[: len(CLASS_NAMES)]
    if np.isclose(x.sum(), 1.0, atol=1e-3) and (x >= -1e-6).all():
        return np.clip(x, 0.0, 1.0)
    e = np.exp(x - np.max(x))
    return e / e.sum()


class InferenceEngine:
    """Uniform predict() across Keras / TFLite / ONNX."""

    def __init__(self, model_path: str | Path):
        self.path = Path(model_path)
        if not self.path.exists():
            raise FileNotFoundError(f"Model not found: {self.path}")
        suffix = self.path.suffix.lower()
        if suffix == ".keras":
            self.kind = "keras"
            self._init_keras()
        elif suffix == ".tflite":
            self.kind = "tflite"
            self._init_tflite()
        elif suffix == ".onnx":
            self.kind = "onnx"
            self._init_onnx()
        else:
            raise ValueError(f"Unsupported model type '{suffix}' (.keras/.tflite/.onnx)")

    # -- constructors -------------------------------------------------------

    def _init_keras(self) -> None:
        import tensorflow as tf

        self.model = tf.keras.models.load_model(self.path)

    def _init_tflite(self) -> None:
        try:
            from tflite_runtime.interpreter import Interpreter  # type: ignore
        except ImportError:
            import tensorflow as tf  # type: ignore

            Interpreter = tf.lite.Interpreter
        self.interpreter = Interpreter(model_path=str(self.path))
        self.interpreter.allocate_tensors()
        self.inp = self.interpreter.get_input_details()[0]
        self.out = self.interpreter.get_output_details()[0]

    def _init_onnx(self) -> None:
        import onnxruntime as ort

        self.session = ort.InferenceSession(
            str(self.path), providers=["CPUExecutionProvider"]
        )
        self.inp_name = self.session.get_inputs()[0].name

    # -- inference ----------------------------------------------------------

    def predict_batch(self, batch: np.ndarray) -> np.ndarray:
        """(N,224,224,3) float in [-1,1] → (N,3) probabilities."""
        if self.kind == "keras":
            return np.asarray(self.model.predict(batch, verbose=0), dtype=np.float64)

        if self.kind == "onnx":
            out = self.session.run(None, {self.inp_name: batch.astype(np.float32)})[0]
            return np.stack([_ensure_probs(row) for row in out])

        # tflite — handle float32 and quantised (uint8/int8) inputs
        results = []
        dtype = self.inp["dtype"]
        for i in range(batch.shape[0]):
            x = batch[i : i + 1]
            if dtype == np.uint8:
                scale, zero = self.inp.get("quantization", (0.0, 0))
                x = (x / scale + zero).clip(0, 255).astype(np.uint8)
            elif dtype == np.int8:
                scale, zero = self.inp.get("quantization", (0.0, 0))
                x = (x / scale + zero).clip(-128, 127).astype(np.int8)
            else:
                x = x.astype(np.float32)
            self.interpreter.set_tensor(self.inp["index"], x)
            self.interpreter.invoke()
            y = self.interpreter.get_tensor(self.out["index"])[0]
            if self.out["dtype"] in (np.uint8, np.int8):
                y_scale, y_zero = self.out.get("quantization", (0.0, 0))
                if y_scale:
                    y = (y.astype(np.float64) - y_zero) * y_scale
            results.append(_ensure_probs(y))
        return np.stack(results)

    def predict(self, image_path: str | Path) -> dict:
        """Single image → {label, confidence, all_probabilities} JSON-ready."""
        probs = self.predict_batch(preprocess(image_path))[0]
        idx = int(np.argmax(probs))
        return {
            "label": CLASS_NAMES[idx],
            "confidence": round(float(probs[idx]), 4),
            "all_probabilities": {
                name: round(float(p), 4) for name, p in zip(CLASS_NAMES, probs)
            },
        }

    def latency_ms(self, warmup: int = 5, runs: int = 30) -> float:
        """Mean single-image inference latency in milliseconds.

        Uses a zero tensor — latency depends on input shape, not content.
        """
        x = np.zeros((1, *IMG_SIZE, 3), dtype=np.float32)
        for _ in range(warmup):
            self.predict_batch(x)
        start = time.perf_counter()
        for _ in range(runs):
            self.predict_batch(x)
        return (time.perf_counter() - start) / runs * 1000.0
