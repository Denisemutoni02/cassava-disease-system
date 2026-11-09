"""Risk Logic Engine.

Turns a raw CNN prediction (label + confidence) into:
* a final disease label – low confidence becomes ``Uncertain``
* a severity level (Low / Moderate / High)
* practical farmer-facing advice text

Rules live in the ``risk_rules`` table so admins can tune thresholds and
advice templates without redeploying. Built-in defaults are used when the
table is empty (e.g. first boot or unit tests).
"""

from dataclasses import dataclass

# Default templates (used until DB rules are seeded)
DEFAULT_RULES: dict[str, dict] = {
    "CMD": {
        "min_confidence": 0.60,
        "severity_level": "Moderate",
        "advice_template": (
            "Cassava Mosaic Disease (CMD) detected with {confidence:.0%} confidence.\n"
            "• Remove and burn infected plants to reduce inoculum.\n"
            "• Use certified disease-free planting material (cuttings).\n"
            "• Control whitefly vectors; avoid planting near infected fields.\n"
            "• Report the case to your MuZARDI extension officer."
        ),
    },
    "CBSD": {
        "min_confidence": 0.60,
        "severity_level": "High",
        "advice_template": (
            "Cassava Brown Streak Disease (CBSD) detected with {confidence:.0%} confidence.\n"
            "• Rogue (uproot and destroy) infected plants immediately.\n"
            "• Plant only certified clean seedlings from resistant varieties.\n"
            "• Monitor neighbouring fields – CBSD spreads through cuttings and whiteflies.\n"
            "• Report to MuZARDI so the hotspot can be tracked on the outbreak map."
        ),
    },
    "Healthy": {
        "min_confidence": 0.60,
        "severity_level": "Low",
        "advice_template": (
            "The leaf appears healthy ({confidence:.0%} confidence).\n"
            "• Continue routine scouting every 1–2 weeks.\n"
            "• Keep using disease-free planting material.\n"
            "• Share healthy-field practices with neighbouring farmers."
        ),
    },
    "Uncertain": {
        "min_confidence": 0.0,
        "severity_level": "Low",
        "advice_template": (
            "We could not identify the disease with enough confidence "
            "({confidence:.0%}).\n"
            "• Retake the photo in daylight, one leaf filling the frame.\n"
            "• Avoid shadows and hold the camera steady.\n"
            "• Ask a MuZARDI extension officer to verify this case."
        ),
    },
}


@dataclass(frozen=True)
class RiskResult:
    final_label: str      # CMD | CBSD | Healthy | Uncertain
    severity_level: str   # Low | Moderate | High
    advice_text: str
    is_confident: bool


class RiskEngine:
    """Evaluate predictions against risk rules."""

    def __init__(self, rules: list[dict] | None = None):
        # rules: [{"disease_label","min_confidence","severity_level","advice_template"}, ...]
        self.rules: dict[str, dict] = {}
        for r in rules or []:
            if r.get("is_active", True):
                self.rules[r["disease_label"]] = r
        if not self.rules:
            self.rules = {k: dict(v, disease_label=k) for k, v in DEFAULT_RULES.items()}

    def evaluate(self, raw_label: str, confidence: float, threshold: float) -> RiskResult:
        """Map a raw model output to label + severity + advice."""
        rule = self.rules.get(raw_label, DEFAULT_RULES.get(raw_label, DEFAULT_RULES["Uncertain"]))
        min_conf = float(rule.get("min_confidence", threshold))

        if confidence < max(min_conf, threshold):
            final_label = "Uncertain"
            rule = self.rules.get("Uncertain", DEFAULT_RULES["Uncertain"])
            is_confident = False
        else:
            final_label = raw_label
            is_confident = raw_label != "Uncertain"

        text = rule["advice_template"].format(confidence=confidence * 100 / 100)
        # Template uses {confidence:.0%} so pass fraction; fix double formatting
        text = rule["advice_template"].format(confidence=confidence)

        return RiskResult(
            final_label=final_label,
            severity_level=rule["severity_level"],
            advice_text=text,
            is_confident=is_confident,
        )


async def load_rules_from_db(db) -> list[dict]:
    """Fetch active rules from the database (empty list if unavailable)."""
    from sqlalchemy import select

    from app.models import RiskRule

    result = await db.execute(select(RiskRule).where(RiskRule.is_active.is_(True)))
    rows = result.scalars().all()
    return [
        {
            "disease_label": r.disease_label,
            "min_confidence": r.min_confidence,
            "severity_level": r.severity_level,
            "advice_template": r.advice_template,
            "is_active": r.is_active,
        }
        for r in rows
    ]
