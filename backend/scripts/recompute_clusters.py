"""Recompute DBSCAN hotspot clusters from recent positive diagnoses.

Reads confident CMD/CBSD diagnoses (with GPS) from the last
CLUSTER_WINDOW_DAYS days, clusters them with scikit-learn DBSCAN
(haversine metric), and replaces the rows in ``hotspot_clusters`` +
``cluster_members``.

Run from the backend directory:

    python scripts/recompute_clusters.py
    python scripts/recompute_clusters.py --eps 1500 --min-samples 4 --window-days 30
    python scripts/recompute_clusters.py --geojson hotspots.geojson

Configuration comes from the environment (.env): DATABASE_URL,
CLUSTER_EPS_M, CLUSTER_MIN_SAMPLES, CLUSTER_WINDOW_DAYS.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import HotspotCluster  # noqa: E402
from app.services.clustering import (  # noqa: E402
    clusters_to_geojson,
    load_positive_points,
    recompute_clusters,
)


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--eps", type=float, default=settings.cluster_eps_m,
                   help=f"DBSCAN neighbourhood radius in metres (default {settings.cluster_eps_m})")
    p.add_argument("--min-samples", type=int, default=settings.cluster_min_samples,
                   help=f"Minimum diagnoses to form a hotspot (default {settings.cluster_min_samples})")
    p.add_argument("--window-days", type=int, default=settings.cluster_window_days,
                   help=f"Only consider diagnoses from this many days (default {settings.cluster_window_days})")
    p.add_argument("--geojson", metavar="PATH", default=None,
                   help="Also write the resulting FeatureCollection to this JSON file")
    return p.parse_args()


async def main() -> int:
    args = parse_args()

    async with SessionLocal() as db:
        points = await load_positive_points(db, window_days=args.window_days)
        print(f"Input: {len(points)} positive CMD/CBSD diagnoses "
              f"(last {args.window_days} days, with GPS)")

        clusters = await recompute_clusters(
            db,
            eps_m=args.eps,
            min_samples=args.min_samples,
            window_days=args.window_days,
        )
        await db.commit()

        print(f"Clusters written: {len(clusters)} "
              f"(eps={args.eps} m, min_samples={args.min_samples}, algorithm=DBSCAN)")
        for c in clusters:
            print(f"  {c.dominant_disease:<5} {c.member_count:>3} cases  "
                  f"r={c.radius_m:>7.1f} m  risk={c.risk_level:<9} "
                  f"centroid=({c.latitude:.5f}, {c.longitude:.5f})")

        if args.geojson:
            rows = (await db.execute(select(HotspotCluster))).scalars().all()
            geo = clusters_to_geojson(rows)
            Path(args.geojson).write_text(json.dumps(geo, indent=2), encoding="utf-8")
            print(f"GeoJSON written: {args.geojson} ({len(geo['features'])} features)")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
