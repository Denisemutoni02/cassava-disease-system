"""Schemas for farms, diagnoses and advice."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FarmCreate(BaseModel):
    farm_name: str = Field(min_length=2, max_length=120)
    district: str | None = Field(default=None, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class FarmOut(BaseModel):
    farm_id: uuid.UUID
    farm_name: str
    district: str | None
    latitude: float | None
    longitude: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdviceOut(BaseModel):
    advice_id: uuid.UUID
    advice_text: str
    severity_level: str
    generated_at: datetime

    model_config = {"from_attributes": True}


class DiagnosisOut(BaseModel):
    diagnosis_id: uuid.UUID
    image_id: uuid.UUID
    disease_label: str
    confidence_score: float
    inferred_at: datetime
    latitude: float | None
    longitude: float | None
    advice: AdviceOut | None = None


class DiagnosisCreateResponse(BaseModel):
    """Full response returned by POST /diagnoses."""

    diagnosis: DiagnosisOut
    nearby_hotspots: int = 0
    hotspot_message: str | None = None
    model_version: str = "mock"


class DiagnosisPage(BaseModel):
    items: list[DiagnosisOut]
    total: int
    page: int
    page_size: int
