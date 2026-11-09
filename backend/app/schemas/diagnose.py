"""Pydantic schemas for the standalone POST /diagnose endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiagnoseResponse(BaseModel):
    """Response of ``POST /diagnose``.

    Field order matches the documented example payload.
    """

    label: str = Field(
        description="Predicted class: Healthy | CMD | CBSD",
        json_schema_extra={"example": "CMD"},
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Softmax confidence of the predicted class (0..1)",
        json_schema_extra={"example": 0.93},
    )
    advice: str = Field(
        description="Rule-based farmer-facing advice (softened when confidence < 0.70)",
    )
    all_probabilities: dict[str, float] = Field(
        description="Probability per class, keys ordered CBSD, CMD, Healthy",
        json_schema_extra={"example": {"Healthy": 0.02, "CMD": 0.93, "CBSD": 0.05}},
    )
    latitude: float | None = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Echo of the uploaded GPS latitude (null when omitted)",
        json_schema_extra={"example": 0.35},
    )
    longitude: float | None = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Echo of the uploaded GPS longitude (null when omitted)",
        json_schema_extra={"example": 32.75},
    )
    diagnosis_id: str | None = Field(
        default=None,
        description="UUID of the saved diagnosis row (null only if saving failed)",
        json_schema_extra={"example": "6f9d1f5a-1a5a-4a5a-9a5a-6f9d1f5a1a5a"},
    )
    nearby_hotspots: int = Field(
        default=0,
        description="Outbreak clusters within 5 km of the uploaded GPS point",
        json_schema_extra={"example": 2},
    )
    hotspot_message: str | None = Field(
        default=None,
        description="Human-readable cluster summary (null when no cluster nearby)",
        json_schema_extra={"example": "2 hotspot cluster(s) within 5 km of this location."},
    )
    model_version: str = Field(
        default="",
        description="Model artefact tag that produced the prediction",
        json_schema_extra={"example": "onnx-mobilenetv2_cassava"},
    )
