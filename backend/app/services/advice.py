"""Rule-based risk advice for the standalone POST /diagnose endpoint.

Deliberately database-free: the endpoint must work before PostgreSQL/PostGIS
exists. One short, farmer-facing sentence-group per class, plus a softer,
confidence-aware tone when the model is unsure (< LOW_CONFIDENCE_THRESHOLD).
"""

from __future__ import annotations

# Below this confidence the advice switches to a "preliminary result" tone.
LOW_CONFIDENCE_THRESHOLD = 0.70

ADVICE_RULES: dict[str, str] = {
    "Healthy": (
        "This leaf looks healthy. Keep scouting every 1-2 weeks, use only "
        "certified disease-free cuttings, and remove infected volunteers to "
        "keep your field this way."
    ),
    "CMD": (
        "Avoid using this plant for cuttings. Remove heavily affected leaves "
        "and contact a MuZARDI extension officer."
    ),
    "CBSD": (
        "Strong warning: CBSD attacks the roots and tubers, so yield can be "
        "lost even when the leaves look mildly affected. Uproot and destroy "
        "heavily affected plants, do not use them for cuttings, and contact "
        "a MuZARDI extension officer immediately."
    ),
}

UNKNOWN_ADVICE = (
    "The model could not classify this leaf. Retake the photo in good "
    "daylight with one leaf filling the frame, or contact a MuZARDI "
    "extension officer."
)


def build_advice(label: str, confidence: float) -> str:
    """Return farmer-facing advice for a prediction.

    * ``Healthy`` / ``CMD`` / ``CBSD`` → the matching rule.
    * confidence < 0.70 → rule text is prefixed with a cautious,
      confidence-aware wording and a retake-the-photo instruction.
    * unknown label → generic fallback.
    """
    base = ADVICE_RULES.get(label, UNKNOWN_ADVICE)

    if confidence < LOW_CONFIDENCE_THRESHOLD:
        return (
            f"Low confidence ({confidence:.0%}) - this leaf may be {label}, "
            f"but treat it as a preliminary result. {base} "
            "Retake the photo in good daylight (one leaf filling the frame, "
            "no shadows) and submit again for a more reliable answer."
        )
    return base
