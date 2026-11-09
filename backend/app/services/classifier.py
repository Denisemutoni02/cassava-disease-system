"""Leaf classifier service.

Loads a post-training-quantised MobileNetV2 model from disk and runs
server-side inference. Supported artefacts, in priority order:

1. TFLite  (``.tflite``)  – primary deliverable, needs ``tflite-runtime`` or TF
2. ONNX    (``.onnx``)    – fallback, needs ``onnxruntime``
3. Mock                   – deterministic hash-based predictor so the whole
                            system (API, UI, clustering, tests) can be
                            demonstrated without a trained model on disk.

The mock is clearly reported via ``Classifier.mode`` ("tflite" | "onnx" | "mock")
so the admin console and API docs can surface it.
"""

import hashlib
import io
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)

CLASS_NAMES = ["CBSD", "CMD", "Healthy"]  # alphabetical, matches training export
INPUT_SIZE = (224, 224)


@dataclass(frozen=True)
class Prediction:
    label: str          # one of CLASS_NAMES
    confidence: float   # 0..1
    mode: str           # tflite | onnx | mock
    model_version: str
    all_probabilities: dict[str, float] | None = None  # {class: prob}


def preprocess_image(data: bytes) -> np.ndarray:
    """Decode image bytes → float32 batch of shape (1, 224, 224, 3) in [-1, 1].

    Normalisation matches ``keras.applications.mobilenet_v2.preprocess_input``
    used during training.
    """
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img = img.resize(INPUT_SIZE, Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32)
    arr = (arr / 127.5) - 1.0
    return np.expand_dims(arr, axis=0)


class MockClassifier:
    """Deterministic pseudo-classifier used when no model file is available.

    The predicted class and confidence are derived from the SHA-256 of the
    image bytes so the same photo always yields the same result (handy for
    demos and tests) while different photos spread across all three classes.
    """

    mode = "mock"
    version_tag = "mock-v1"

    def predict(self, image_bytes: bytes) -> Prediction:
        digest = hashlib.sha256(image_bytes).digest()
        class_idx = digest[0] % len(CLASS_NAMES)
        # Confidence spread in [0.62, 0.97] so results are "confident"
        confidence = round(0.62 + (digest[1] / 255.0) * 0.35, 4)
        remainder = round(1.0 - confidence, 4)
        others = [i for i in range(len(CLASS_NAMES)) if i != class_idx]
        probs = {name: 0.0 for name in CLASS_NAMES}
        probs[CLASS_NAMES[class_idx]] = confidence
        for i in others:
            probs[CLASS_NAMES[i]] = round(remainder / len(others), 4)
        return Prediction(
            label=CLASS_NAMES[class_idx],
            confidence=confidence,
            mode=self.mode,
            model_version=self.version_tag,
            all_probabilities=probs,
        )


class TFLiteClassifier:
    """Quantised TFLite MobileNetV2 inference."""

    mode = "tflite"

    def __init__(self, model_path: Path):
        try:
            from tflite_runtime.interpreter import Interpreter  # type: ignore
        except ImportError:  # pragma: no cover - depends on environment
            import tensorflow as tf  # type: ignore

            Interpreter = tf.lite.Interpreter

        self.interpreter = Interpreter(model_path=str(model_path))
        self.interpreter.allocate_tensors()
        self._input = self.interpreter.get_input_details()[0]
        self._output = self.interpreter.get_output_details()[0]
        self.version_tag = f"tflite-{model_path.stem}"

    def predict(self, image_bytes: bytes) -> Prediction:
        batch = preprocess_image(image_bytes)
        # Quantised models may expect int8 input; scale if needed.
        if self._input["dtype"] == np.int8:
            scale, zero = self._input.get("quantization", (0.0, 0))
            batch = (batch / scale + zero).clip(-128, 127).astype(np.int8)
        self.interpreter.set_tensor(self._input["index"], batch)
        self.interpreter.invoke()
        probs = np.asarray(self.interpreter.get_tensor(self._output["index"])[0], dtype=np.float64)
        probs = probs.reshape(-1)[: len(CLASS_NAMES)]
        probs = _ensure_probs(probs)
        idx = int(np.argmax(probs))
        return Prediction(
            label=CLASS_NAMES[idx],
            confidence=float(probs[idx]),
            mode=self.mode,
            model_version=self.version_tag,
            all_probabilities=_prob_dict(probs),
        )


class OnnxClassifier:
    """Float/quantised ONNX MobileNetV2 inference (fallback)."""

    mode = "onnx"

    def __init__(self, model_path: Path):
        import onnxruntime as ort  # type: ignore

        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self._input_name = self.session.get_inputs()[0].name
        self.version_tag = f"onnx-{model_path.stem}"

    def predict(self, image_bytes: bytes) -> Prediction:
        batch = preprocess_image(image_bytes).astype(np.float32)
        outputs = self.session.run(None, {self._input_name: batch})
        probs = np.asarray(outputs[0][0], dtype=np.float64).reshape(-1)[: len(CLASS_NAMES)]
        probs = _ensure_probs(probs)
        idx = int(np.argmax(probs))
        return Prediction(
            label=CLASS_NAMES[idx],
            confidence=float(probs[idx]),
            mode=self.mode,
            model_version=self.version_tag,
            all_probabilities=_prob_dict(probs),
        )


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


def _prob_dict(probs: np.ndarray) -> dict[str, float]:
    """Probability vector → {class_name: probability} in canonical class order."""
    return {name: round(float(p), 4) for name, p in zip(CLASS_NAMES, probs)}


def _ensure_probs(x: np.ndarray) -> np.ndarray:
    """Return a proper probability vector.

    The trained model already ends in softmax, so outputs usually sum to ~1.
    Only apply softmax when we receive raw logits (sum far from 1).
    """
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    if x.size == 0:
        return x
    if np.isclose(x.sum(), 1.0, atol=1e-3) and (x >= -1e-6).all():
        return np.clip(x, 0.0, 1.0)
    return _softmax(x)


class Classifier:
    """Facade that picks the best available backend at construction time."""

    def __init__(self, model_path: Path, force_mock: bool = False):
        self.mode = "mock"
        self._impl: MockClassifier | TFLiteClassifier | OnnxClassifier = MockClassifier()

        if force_mock:
            logger.info("Classifier running in forced MOCK mode")
            return

        if model_path.exists():
            suffix = model_path.suffix.lower()
            try:
                if suffix == ".tflite":
                    self._impl = TFLiteClassifier(model_path)
                elif suffix == ".onnx":
                    self._impl = OnnxClassifier(model_path)
                else:
                    logger.warning("Unknown model extension %r – using mock", suffix)
                self.mode = self._impl.mode
                logger.info("Classifier loaded (%s) from %s", self.mode, model_path)
                return
            except Exception as exc:  # pragma: no cover - env dependent
                logger.warning("Failed to load model %s (%s) – falling back to mock", model_path, exc)
        else:
            logger.warning("Model file not found at %s – using mock classifier", model_path)

    @property
    def version_tag(self) -> str:
        return self._impl.version_tag

    def predict(self, image_bytes: bytes) -> Prediction:
        return self._impl.predict(image_bytes)


_classifier: Classifier | None = None


def get_classifier() -> Classifier:
    """Process-wide singleton (loaded once per worker)."""
    global _classifier
    if _classifier is None:
        settings = get_settings()
        _classifier = Classifier(settings.model_file, force_mock=settings.force_mock_model)
    return _classifier


def reset_classifier_singleton() -> None:
    """Test helper – force a reload on next access."""
    global _classifier
    _classifier = None
