# Architecture

## Layers (matches the project system-architecture diagram)

| Layer | Components |
|-------|------------|
| **Presentation** | React PWA (Vite): Login/Register, Home, Upload, Result, Map, History, Admin. Leaflet + OpenStreetMap tiles. Service worker caches the **app shell only**. |
| **Application** | FastAPI behind Nginx/TLS. JWT auth + RBAC (`farmer` / `officer` / `admin`), image validation, diagnosis orchestrator, risk advice, GeoJSON cluster API, admin/monitoring API. |
| **Intelligence** | Quantised MobileNetV2 CNN (TFLite, server-side), Risk Logic Engine (DB rules), DBSCAN geospatial clustering (background task). |
| **Data** | PostgreSQL + PostGIS (GiST indexes on every geography column), leaf photo files on disk, model registry table, audit-friendly timestamps. |

## Diagnosis request flow

1. PWA collects image (+ optional GPS/farm) → `POST /api/v1/diagnoses` with JWT.
2. Backend validates type/size/resolution → stores file → inserts `leaf_images`.
3. `Classifier.predict()` runs the quantised model → raw label + confidence.
4. `RiskEngine.evaluate()` applies threshold + DB rules → final label
   (`Uncertain` if below threshold), severity, advice text.
5. `diagnoses` + `advice` rows are committed; response returns immediately.
6. If the result is confident CMD/CBSD **and** has GPS, a FastAPI
   `BackgroundTask` recomputes DBSCAN clusters (farmer never waits for it).
7. PWA renders the result + advice and links to the hotspot map.

## Clustering design

- **Input**: diagnoses from the last `CLUSTER_WINDOW_DAYS` (90) whose label is
  CMD or CBSD and that carry GPS.
- **Algorithm**: scikit-learn `DBSCAN(metric="haversine")`; coordinates are
  converted to radians; `eps = CLUSTER_EPS_M / 6371000`.
- **Noise** (label −1) is discarded: isolated single cases do not form hotspots.
- Each cluster stores centroid (lat/lon + PostGIS point), radius (farthest
  member), member count, dominant disease, risk level
  (`High ≥10 · Emerging ≥5 · Low ≥3`) and the parameters used.
- Old clusters are replaced wholesale on each recompute (derived data).
- `GET /clusters/geojson` serialises the table for Leaflet; circle radius on
  the map comes from `properties.radius_m`.

## Security

- Passwords: bcrypt. Tokens: HS256 JWT with `sub` (user id) + `role`, expiry
  `ACCESS_TOKEN_EXPIRE_MINUTES` (default 24 h).
- Role guards: `require_role("officer","admin")` / `require_role("admin")`.
- Farmers see only their own history; staff may query `scope=all`.
- CORS restricted to configured origins; TLS terminated at the reverse proxy.
- Uploads: MIME allow-list, size cap, structural decode check, min resolution,
  random UUID filenames outside the web root.

## Online-only rationale

Diagnosis quality depends on the server-side model; hotspot mapping requires
shared state across farms. The PWA therefore:
- blocks submission while `navigator.onLine === false` and shows a persistent banner,
- treats `fetch` network failures as `NetworkError` with a clear message,
- never queues uploads locally (no offline-first logic by design).

## Scaling notes

- Uvicorn workers are stateless; the model is loaded once per worker.
- Clustering is O(n) per recompute with n = recent positive GPS diagnoses —
  fine for district-scale deployments. For national scale, move recomputes to
  a periodic Celery/cron job and add a spatial bbox filter using the GiST index.
- Store leaf files on a shared volume or object storage (swap `storage.py`).
