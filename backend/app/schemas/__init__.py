"""Pydantic request/response schemas."""

from app.schemas.admin import AdminStats, ModelVersionOut, UserAdminOut
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.schemas.cluster import ClusterOut, ClustersGeoJSON
from app.schemas.diagnosis import (
    AdviceOut,
    DiagnosisCreateResponse,
    DiagnosisOut,
    DiagnosisPage,
    FarmCreate,
    FarmOut,
)

__all__ = [
    "LoginRequest",
    "RegisterRequest",
    "TokenResponse",
    "UserOut",
    "FarmCreate",
    "FarmOut",
    "AdviceOut",
    "DiagnosisOut",
    "DiagnosisCreateResponse",
    "DiagnosisPage",
    "ClusterOut",
    "ClustersGeoJSON",
    "AdminStats",
    "ModelVersionOut",
    "UserAdminOut",
]
