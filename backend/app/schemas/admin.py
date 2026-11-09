"""Admin-area schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class UserAdminOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ModelVersionOut(BaseModel):
    model_version_id: uuid.UUID
    version_tag: str
    architecture: str
    file_path: str | None
    val_accuracy: float | None
    is_active: bool
    deployed_at: datetime

    model_config = {"from_attributes": True}


class AdminStats(BaseModel):
    users: int
    farmers: int
    officers: int
    diagnoses_total: int
    diagnoses_cmd: int
    diagnoses_cbsd: int
    diagnoses_healthy: int
    diagnoses_uncertain: int
    active_clusters: int
    active_model: ModelVersionOut | None
    classifier_mode: str
