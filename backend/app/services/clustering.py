"""Geospatial clustering service (DBSCAN).

Only *confident* CMD/CBSD diagnoses (recent, with GPS) feed the hotspots.
Coordinates are clustered in radians using scikit-learn's haversine metric,
which is accurate for the local (Ugandan) scale of this deployment.
Results are persisted to ``hotspot_clusters`` + ``cluster_members`` and
exposed to the map as GeoJSON.
"""

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClusterMember, Diagnosis, HotspotCluster, LeafImage

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class ClusterResult:
    cluster_id: uuid.UUID
    latitude: float
    longitude: float
    radius_m: float
    member_count: int
    dominant_disease: str
    risk_level: str
    member_diagnosis_ids: list[uuid.UUID]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points ( kilometres )."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M / 1000.0 * math.asin(math.sqrt(a))


def risk_level_for(member_count: int) -> str:
    """Map cluster size to the risk vocabulary used by the UI."""
    if member_count >= 10:
        return "High"
    if member_count >= 5:
        return "Emerging"
    return "Low"


def run_dbscan(
    points: list[tuple[float, float, str, uuid.UUID]],
    eps_m: float,
    min_samples: int,
) -> list[ClusterResult]:
    """Cluster (lat, lon, label, diagnosis_id) tuples with DBSCAN.

    Returns one ClusterResult per non-noise cluster. Noise points (label -1)
    are discarded – single isolated cases do not form hotspots.
    """
    if len(points) < min_samples:
        return []

    from sklearn.cluster import DBSCAN

    lats = np.array([p[0] for p in points])
    lons = np.array([p[1] for p in points])
    coords_rad = np.radians(np.column_stack([lats, lons]))

    eps_rad = eps_m / EARTH_RADIUS_M
    clustering = DBSCAN(eps=eps_rad, min_samples=min_samples, metric="haversine").fit(coords_rad)
    labels = clustering.labels_

    results: list[ClusterResult] = []
    for label_id in sorted(set(labels)):
        if label_id == -1:
            continue
        idx = np.where(labels == label_id)[0]
        member_ids = [points[i][3] for i in idx]
        c_lats = lats[idx]
        c_lons = lons[idx]
        centroid_lat = float(c_lats.mean())
        centroid_lon = float(c_lons.mean())
        # radius = farthest member from centroid
        radius_m = max(
            haversine_km(centroid_lat, centroid_lon, float(lats[i]), float(lons[i])) * 1000.0
            for i in idx
        )
        # dominant disease = most frequent label among members
        member_labels = [points[i][2] for i in idx]
        dominant = max(set(member_labels), key=member_labels.count)
        results.append(
            ClusterResult(
                cluster_id=uuid.uuid4(),
                latitude=centroid_lat,
                longitude=centroid_lon,
                radius_m=round(max(radius_m, 50.0), 1),  # floor 50 m for visibility
                member_count=len(idx),
                dominant_disease=dominant,
                risk_level=risk_level_for(len(idx)),
                member_diagnosis_ids=member_ids,
            )
        )
    return results


async def load_positive_points(
    db: AsyncSession,
    window_days: int,
) -> list[tuple[float, float, str, uuid.UUID]]:
    """Fetch recent, confident CMD/CBSD diagnoses that carry GPS coordinates."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    stmt = (
        select(
            LeafImage.latitude,
            LeafImage.longitude,
            Diagnosis.disease_label,
            Diagnosis.diagnosis_id,
        )
        .join(LeafImage, Diagnosis.image_id == LeafImage.image_id)
        .where(
            Diagnosis.disease_label.in_(["CMD", "CBSD"]),
            Diagnosis.confidence_score >= 0.0,  # label already reflects confidence gate
            Diagnosis.inferred_at >= since,
            LeafImage.latitude.isnot(None),
            LeafImage.longitude.isnot(None),
        )
    )
    rows = (await db.execute(stmt)).all()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


async def recompute_clusters(
    db: AsyncSession,
    eps_m: float = 2000.0,
    min_samples: int = 3,
    window_days: int = 90,
) -> list[ClusterResult]:
    """Rebuild all hotspot clusters from scratch and persist them."""
    points = await load_positive_points(db, window_days=window_days)
    clusters = run_dbscan(points, eps_m=eps_m, min_samples=min_samples)
    logger.info("Clustering: %d points → %d clusters", len(points), len(clusters))

    # Replace previously computed clusters atomically-ish (background task)
    existing = (await db.execute(select(HotspotCluster.cluster_id))).scalars().all()
    if existing:
        await db.execute(delete(ClusterMember).where(ClusterMember.cluster_id.in_(existing)))
        await db.execute(delete(HotspotCluster).where(HotspotCluster.cluster_id.in_(existing)))

    now = datetime.now(timezone.utc)
    for c in clusters:
        cluster = HotspotCluster(
            cluster_id=c.cluster_id,
            latitude=c.latitude,
            longitude=c.longitude,
            radius_m=c.radius_m,
            member_count=c.member_count,
            dominant_disease=c.dominant_disease,
            risk_level=c.risk_level,
            algorithm="DBSCAN",
            eps_m=eps_m,
            min_samples=min_samples,
            computed_at=now,
        )
        # Keep the PostGIS geography column in sync when running on PostgreSQL
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            from geoalchemy2.elements import WKTElement

            cluster.centroid = WKTElement(
                f"POINT({c.longitude} {c.latitude})", srid=4326
            )
        db.add(cluster)
        for did in c.member_diagnosis_ids:
            db.add(ClusterMember(cluster_id=c.cluster_id, diagnosis_id=did))

    await db.flush()
    return clusters


async def count_hotspots_near(
    db: AsyncSession,
    latitude: float,
    longitude: float,
    radius_km: float = 5.0,
) -> int:
    """Count stored clusters whose centroid lies within radius_km of a point."""
    result = await db.execute(select(HotspotCluster))
    clusters = result.scalars().all()
    n = 0
    for c in clusters:
        if haversine_km(latitude, longitude, c.latitude, c.longitude) <= radius_km:
            n += 1
    return n


def clusters_to_geojson(clusters: list[HotspotCluster]) -> dict:
    """Serialize ORM clusters as a GeoJSON FeatureCollection for Leaflet."""
    features = []
    for c in clusters:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [c.longitude, c.latitude],  # GeoJSON = [lon, lat]
                },
                "properties": {
                    "cluster_id": str(c.cluster_id),
                    "dominant_disease": c.dominant_disease,
                    "risk_level": c.risk_level,
                    "member_count": c.member_count,
                    "radius_m": c.radius_m,
                    "algorithm": c.algorithm,
                    "eps_m": c.eps_m,
                    "min_samples": c.min_samples,
                    "computed_at": c.computed_at.isoformat() if c.computed_at else None,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
