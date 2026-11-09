"""SQLAlchemy ORM models (mirrors backend/app/db/schema.sql)."""

from app.models.entities import (
    Advice,
    ClusterMember,
    Diagnosis,
    DiagnosisFeedback,
    Farm,
    HotspotCluster,
    LeafImage,
    ModelVersion,
    RiskRule,
    User,
)

__all__ = [
    "User",
    "Farm",
    "ModelVersion",
    "LeafImage",
    "Diagnosis",
    "Advice",
    "RiskRule",
    "HotspotCluster",
    "ClusterMember",
    "DiagnosisFeedback",
]
