"""Hotspot cluster endpoints (GeoJSON for the Leaflet map)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DbSession, StaffUser
from app.models import HotspotCluster
from app.schemas.cluster import ClusterOut, ClustersGeoJSON
from app.services.clustering import clusters_to_geojson, recompute_clusters

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get(
    "/geojson",
    response_model=ClustersGeoJSON,
    summary="Hotspot clusters as GeoJSON FeatureCollection",
)
async def clusters_geojson(
    db: DbSession,
    disease: Annotated[str | None, Query(pattern="^(CMD|CBSD|Healthy)$")] = None,
) -> ClustersGeoJSON:
    """Colour-coded risk clusters for the interactive map.

    Each feature is a Point (cluster centroid) whose radius circle is drawn
    client-side from the ``radius_m`` property.
    """
    stmt = select(HotspotCluster).order_by(HotspotCluster.member_count.desc())
    if disease:
        stmt = stmt.where(HotspotCluster.dominant_disease == disease)
    clusters = list((await db.execute(stmt)).scalars().all())
    return ClustersGeoJSON(**clusters_to_geojson(clusters))


@router.get("", response_model=list[ClusterOut], summary="List hotspot clusters")
async def list_clusters(
    db: DbSession,
    disease: Annotated[str | None, Query(pattern="^(CMD|CBSD|Healthy)$")] = None,
) -> list[HotspotCluster]:
    stmt = select(HotspotCluster).order_by(HotspotCluster.member_count.desc())
    if disease:
        stmt = stmt.where(HotspotCluster.dominant_disease == disease)
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/recompute",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
    summary="(Staff) Force a DBSCAN recompute of all hotspots",
)
async def recompute(db: DbSession, user: StaffUser) -> dict:
    """Officer/admin trigger for the clustering background job."""
    settings = get_settings()
    clusters = await recompute_clusters(
        db,
        eps_m=settings.cluster_eps_m,
        min_samples=settings.cluster_min_samples,
        window_days=settings.cluster_window_days,
    )
    if not clusters:
        return {"clusters": 0, "message": "No qualifying GPS-tagged CMD/CBSD diagnoses found."}
    return {"clusters": len(clusters), "message": "Hotspot clusters updated."}


@router.get("/{cluster_id}", response_model=ClusterOut, summary="Get one cluster")
async def get_cluster(cluster_id: str, db: DbSession) -> HotspotCluster:
    cluster = (
        await db.execute(select(HotspotCluster).where(HotspotCluster.cluster_id == cluster_id))
    ).scalar_one_or_none()
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    return cluster
