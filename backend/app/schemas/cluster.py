"""Schemas for hotspot clusters / GeoJSON."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ClusterOut(BaseModel):
    cluster_id: uuid.UUID
    latitude: float
    longitude: float
    radius_m: float
    member_count: int
    dominant_disease: str
    risk_level: str
    algorithm: str
    eps_m: float
    min_samples: int
    computed_at: datetime

    model_config = {"from_attributes": True}


class ClustersGeoJSON(BaseModel):
    """FeatureCollection consumed by the Leaflet map."""

    type: str = "FeatureCollection"
    features: list[dict[str, Any]]
