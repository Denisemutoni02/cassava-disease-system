# Database, PostGIS & Hotspot Clustering

Data layer for the cassava disease system: PostgreSQL + PostGIS for GPS,
DBSCAN clustering for outbreak hotspots, GeoJSON for the map.

## 1. Tables

| Table | Purpose | Spatial column |
|-------|---------|----------------|
| `users` | Farmers / officers / admins | — |
| `farms` | Farm plots owned by users | `location` GEOGRAPHY(Point, 4326) |
| `leaf_images` | Uploaded leaf photos + GPS | `gps_location` GEOGRAPHY(Point, 4326) |
| `diagnoses` | CNN output per image (label, confidence) | — |
| `advice` | Risk-engine advice per diagnosis | — |
| `hotspot_clusters` | DBSCAN-derived outbreak hotspots | `centroid` GEOGRAPHY(Point, 4326) |
| `cluster_members` | Diagnosis ↔ cluster junction | — |
| `model_versions`, `risk_rules`, `diagnosis_feedback` | Registry / config / officer verification | — |

Supporting types: enums `user_role`, `disease_label`, `severity_level`,
`risk_level`. Indexes: **GiST** on every geography column, B-tree on
`diagnoses(disease_label)`, `diagnoses(inferred_at DESC)` and foreign keys.

Triggers keep each `GEOGRAPHY` column in sync with its plain `latitude` /
`longitude` floats, so **any** writer (API, seed script, raw `psql`) lands the
point in PostGIS and the spatial indexes stay usable.

Canonical DDL: `backend/app/db/schema.sql`.

## 2. Enable PostGIS

**Option A — Docker (recommended, matches `docker-compose.yml`):**

```bash
docker compose up -d db          # from the project root
```

Starts `postgis/postgis:16-3.4` on `localhost:5432`
(`cassava` / `cassava` / db `cassava`).

**Option B — native install:**

```bash
# Debian/Ubuntu
sudo apt install postgresql-16-postgis-3
sudo -u postgres psql -c "CREATE USER cassava WITH PASSWORD 'cassava';"
sudo -u postgres psql -c "CREATE DATABASE cassava OWNER cassava;"
```

The extension itself is created by the schema (`CREATE EXTENSION IF NOT
EXISTS postgis;`, superuser required — on a managed instance enable PostGIS
first). Verify:

```bash
psql -U cassava -h localhost -d cassava -c "SELECT PostGIS_Version();"
```

## 3. Configure DATABASE_URL

`backend/.env` (see `backend/.env.example`):

```dotenv
DATABASE_URL=postgresql+asyncpg://cassava:cassava@localhost:5432/cassava
```

SQLite (`sqlite+aiosqlite:///./cassava_guard.db`) still works for dev/tests —
geography columns become TEXT and clustering uses the lat/lon floats, so
behaviour is identical apart from `ST_*` SQL.

## 4. Run migrations

```bash
cd backend
# canonical schema (PostGIS, enums, indexes, triggers)
psql -U cassava -h localhost -d cassava -f app/db/schema.sql

# optional demo data (users, farms, 30+ diagnoses, clusters computed)
..\venv\Scripts\python.exe scripts\seed.py      # Windows
python scripts/seed.py                          # macOS/Linux
```

- Re-running `schema.sql` is safe (idempotent: `IF NOT EXISTS` / `CREATE OR
  REPLACE`).
- `scripts/init_db.py` creates tables from the SQLAlchemy metadata instead —
  fine for SQLite dev/tests, but **prefer `schema.sql` on PostgreSQL** because
  it adds the enums, spatial indexes and triggers.
- Alembic is available in `requirements.txt` if you later want versioned
  migrations; `schema.sql` is the source of truth today.

## 5. Run clustering

DBSCAN over recent, confident CMD/CBSD diagnoses that carry GPS
(scikit-learn, haversine metric, coordinates in radians).

**Settings** (`backend/.env`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `CLUSTER_EPS_M` | `2000` | Neighbourhood radius (metres) |
| `CLUSTER_MIN_SAMPLES` | `3` | Diagnoses needed to form a hotspot |
| `CLUSTER_WINDOW_DAYS` | `90` | Look-back window |

**As a script** (cron-friendly, no auth needed):

```bash
cd backend
python scripts/recompute_clusters.py
python scripts/recompute_clusters.py --eps 1500 --min-samples 4 --window-days 30
python scripts/recompute_clusters.py --geojson hotspots.geojson   # also dump GeoJSON
```

**As an endpoint** (staff JWT; `POST /api/v1/clusters/recompute`) — used by
the admin UI. `scripts/seed.py` also recomputes after seeding.

Each run replaces all rows in `hotspot_clusters` + `cluster_members` and
stamps `computed_at`. Risk level derives from member count:
≥10 → `High`, ≥5 → `Emerging`, else `Low`. Noise points (isolated cases)
are discarded.

## 6. GeoJSON for the map

`GET /api/v1/clusters/geojson` (public) returns:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [32.7551, 0.3518] },
      "properties": {
        "cluster_id": "07d92b27-…",
        "dominant_disease": "CMD",
        "risk_level": "High",
        "member_count": 14,
        "radius_m": 1635.1,
        "algorithm": "DBSCAN",
        "eps_m": 2000.0,
        "min_samples": 3,
        "computed_at": "2026-10-24T20:17:24+00:00"
      }
    }
  ]
}
```

Optional filter: `?disease=CMD|CBSD`. The script's `--geojson` flag produces
the same structure offline.

## 7. Example queries

```sql
-- Hotspots within 5 km of a point (uses the GiST index)
SELECT cluster_id, dominant_disease, risk_level, member_count,
       ST_Distance(centroid, ST_SetSRID(ST_MakePoint(32.58, 0.42), 4326)::geography) AS metres
FROM hotspot_clusters
WHERE ST_DWithin(centroid, ST_SetSRID(ST_MakePoint(32.58, 0.42), 4326)::geography, 5000)
ORDER BY metres;

-- Leaf images with GPS (how clustering sources its points)
SELECT li.image_id, li.latitude, li.longitude, d.disease_label, d.confidence_score
FROM leaf_images li
JOIN diagnoses d ON d.image_id = li.image_id
WHERE d.disease_label IN ('CMD', 'CBSD')
  AND d.inferred_at > now() - INTERVAL '90 days'
  AND li.gps_location IS NOT NULL;

-- Centroid as GeoJSON geometry
SELECT ST_AsGeoJSON(centroid)::json AS geometry FROM hotspot_clusters LIMIT 1;

-- Keep lat/lon and geography in sync manually (normally handled by trigger)
UPDATE farms
SET latitude = 0.42, longitude = 32.58
WHERE farm_id = :id;   -- trigger refreshes `location`

-- Counts by label (admin dashboard)
SELECT disease_label, count(*) FROM diagnoses GROUP BY disease_label;
```

## 8. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `extension "postgis" is not available` | Install the PostGIS package / use the Docker image; `CREATE EXTENSION postgis;` as superuser |
| Clusters never appear | Need ≥ `CLUSTER_MIN_SAMPLES` confident CMD/CBSD diagnoses with GPS within `CLUSTER_EPS_M` — run `scripts/recompute_clusters.py` to see the input count |
| `geography` column always NULL | Trigger missing — re-apply `schema.sql`; columns sync on INSERT/UPDATE of `latitude`/`longitude` |
| Slow map queries | Check the GiST index: `\d+ hotspot_clusters` should list `idx_clusters_centroid` |
| SQLite vs Postgres differences | Spatial SQL (`ST_*`) only exists on PostgreSQL; app code paths are dialect-aware |
