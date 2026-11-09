"""Hotspot GeoJSON endpoint for the Leaflet map (authenticated).

``GET /api/v1/hotspots`` returns the current DBSCAN clusters as a GeoJSON
FeatureCollection — the data source for the frontend map page.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import HotspotCluster
from app.schemas.cluster import ClustersGeoJSON
from app.services.clustering import clusters_to_geojson

router = APIRouter(prefix="/hotspots", tags=["hotspots"])


@router.get(
    "",
    response_model=ClustersGeoJSON,
    summary="Current outbreak hotspots as GeoJSON FeatureCollection (JWT)",
)
async def hotspots(
    db: DbSession,
    user: CurrentUser,
    disease: Annotated[str | None, Query(pattern="^(CMD|CBSD|Healthy)$")] = None,
) -> ClustersGeoJSON:
    """Colour-coded risk clusters for the interactive map.

    Each feature is a Point (cluster centroid) whose radius circle is drawn
    client-side from the ``radius_m`` property. Only authenticated users
    (any role) can read the map data.
    """
    stmt = select(HotspotCluster).order_by(HotspotCluster.member_count.desc())
    if disease:
        stmt = stmt.where(HotspotCluster.dominant_disease == disease)
    clusters = list((await db.execute(stmt)).scalars().all())
    return ClustersGeoJSON(**clusters_to_geojson(clusters))
