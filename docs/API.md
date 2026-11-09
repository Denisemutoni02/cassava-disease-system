# API reference

Base URL: `/api/v1` (except `POST /diagnose` and `GET /health`, which are at
the root). Interactive OpenAPI: `GET /docs` (Swagger UI) and
`GET /redoc`. All endpoints except `POST /auth/*`, `GET /health` and
`GET /clusters/geojson` require `Authorization: Bearer <JWT>`.

Errors are standard FastAPI JSON: `{"detail": "..."}` with appropriate HTTP
status (`401` unauthenticated, `403` forbidden, `404` not found, `409` conflict,
`422` validation).

---

## System

### `GET /health`
```json
{ "status": "ok", "classifier": "tflite", "model_version": "tflite-mobilenetv2_cassava", "online_required": true }
```

---

## Auth

### `POST /auth/register` → `201 TokenResponse`
```json
{
  "full_name": "Peter Okello",
  "password": "Farmer@123",
  "phone": "+256752111222",
  "email": "optional@example.com",
  "role": "farmer"
}
```
Role must be `farmer` or `officer` (public). Returns JWT + user (auto-login).

### `POST /auth/login` → `200 TokenResponse`
```json
{ "identifier": "+256752111222", "password": "Farmer@123" }
```
`identifier` may be phone **or** email.

### `GET /auth/me` → `200 UserOut`

---

## Quick diagnosis (PWA main flow)

### `POST /diagnose` → `200 DiagnoseResponse` — JWT
`multipart/form-data`: `file` (JPEG/PNG/WebP, ≤8 MB) + optional paired
`latitude` / `longitude`. Runs inference, **saves** image → diagnosis → advice
for the caller, queues a background DBSCAN refresh (positive cases with GPS)
and returns the cluster summary.

```json
{
  "label": "Uncertain",
  "confidence": 0.5197,
  "advice": "We could not identify the disease with enough confidence (52%). …",
  "all_probabilities": { "CBSD": 0.5197, "CMD": 0.2625, "Healthy": 0.2178 },
  "latitude": 0.35, "longitude": 32.75,
  "diagnosis_id": "46e76f86-c451-4499-89b3-549bc39c1635",
  "nearby_hotspots": 1,
  "hotspot_message": "1 hotspot cluster(s) within 5 km of this location.",
  "model_version": "onnx-mobilenetv2_cassava"
}
```

`401` without a valid token · `413` too large · `415` wrong content type ·
`422` bad image/GPS · `500` inference failure.

---

## Farms

### `POST /farms` → `201 FarmOut`
```json
{ "farm_name": "Mukono Plot A", "district": "Mukono", "latitude": 0.3533, "longitude": 32.7553 }
```

### `GET /farms` → `200 FarmOut[]` (own farms)
### `GET /farms/{farm_id}` → `200 FarmOut`

---

## Diagnoses (core flow)

### `POST /diagnoses` → `201 DiagnosisCreateResponse`
`multipart/form-data`:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `file` | file | ✔ | JPEG/PNG/WebP, ≤8 MB, ≥64×64 |
| `latitude` | float | | WGS84 |
| `longitude` | float | | WGS84 (must pair with latitude) |
| `gps_accuracy_m` | float | | device-reported accuracy |
| `farm_id` | uuid | | must belong to caller |
| `captured_at` | ISO-8601 | | device capture time |

Response:
```json
{
  "diagnosis": {
    "diagnosis_id": "…",
    "image_id": "…",
    "disease_label": "CMD",
    "confidence_score": 0.92,
    "inferred_at": "2026-10-23T12:00:00Z",
    "latitude": 0.3533,
    "longitude": 32.7553,
    "advice": {
      "advice_id": "…",
      "advice_text": "Cassava Mosaic Disease (CMD) detected with 92% confidence.…",
      "severity_level": "Moderate",
      "generated_at": "…"
    }
  },
  "nearby_hotspots": 1,
  "hotspot_message": "1 hotspot cluster(s) within 5 km of this location.",
  "model_version": "tflite-mobilenetv2_cassava"
}
```

`disease_label` ∈ `CMD | CBSD | Healthy | Uncertain` (low confidence →
`Uncertain`). Confident CMD/CBSD results with GPS trigger a **background**
DBSCAN recompute that does not block this response.

### `GET /diagnoses?page=1&page_size=20&scope=mine|all&label=CMD`
→ `200 DiagnosisPage` `{ items, total, page, page_size }`
Staff (`officer`/`admin`) may use `scope=all`.

### `GET /history?page=1&page_size=50&label=CMD` → `200 DiagnosisPage` — JWT
Alias of `GET /diagnoses?scope=mine` — the logged-in user's past diagnoses,
newest first. Feeds the frontend History page.

### `GET /diagnoses/{id}` → `200 DiagnosisOut`
### `POST /diagnoses/{id}/verify?verified_label=CMD&comments=…` → `200`
Staff only — attaches officer feedback (stored in `diagnosis_feedback`).

---

## Clusters (hotspots)

### `GET /clusters/geojson?disease=CMD` → `200 FeatureCollection`
```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "geometry": { "type": "Point", "coordinates": [32.7551, 0.3515] },
    "properties": {
      "cluster_id": "…",
      "dominant_disease": "CMD",
      "risk_level": "High",
      "member_count": 12,
      "radius_m": 1650.0,
      "algorithm": "DBSCAN",
      "eps_m": 2000.0,
      "min_samples": 3,
      "computed_at": "2026-10-23T12:05:00Z"
    }
  }]
}
```

`risk_level`: `High` (≥10 members) · `Emerging` (≥5) · `Low` (≥3).

### `GET /hotspots?disease=CMD` → `200 FeatureCollection` — JWT
Identical payload to `GET /clusters/geojson`, but requires a token — this is
what the frontend Map page calls.

### `GET /clusters` → `200 ClusterOut[]`
### `GET /clusters/{cluster_id}` → `200 ClusterOut`
### `POST /clusters/recompute` → `202` — staff only, forces DBSCAN now.

---

## Admin (role `admin`; stats also for `officer`)

### `GET /admin/users?role=farmer` → `200 UserAdminOut[]` (admin)
### `PATCH /admin/users/{user_id}/toggle-active` → `200` (admin)
### `GET /admin/model` → `200 ModelVersionOut | null` (admin)
### `GET /admin/stats` → `200 AdminStats`
```json
{
  "users": 5, "farmers": 3, "officers": 1,
  "diagnoses_total": 37, "diagnoses_cmd": 17,
  "diagnoses_cbsd": 7, "diagnoses_healthy": 10, "diagnoses_uncertain": 3,
  "active_clusters": 3,
  "active_model": { "version_tag": "mobilenetv2-quantised-demo", "architecture": "MobileNetV2", "is_active": true, "…": "…" },
  "classifier_mode": "tflite"
}
```

---

## curl smoke test

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"farmer1@example.com","password":"Farmer@123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 1. Diagnose + save (PWA flow) → returns diagnosis_id + cluster summary
curl -s -X POST http://localhost:8000/diagnose \
  -H "Authorization: Bearer $TOKEN" \
  -F file=@data/samples/cmd_leaf.jpg \
  -F latitude=0.3533 -F longitude=32.7553

# 2. The same row appears in the user's history
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/history | python3 -m json.tool | head

# 3. Hotspot clusters for the map (JWT)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/hotspots | python3 -m json.tool | head

# 4. Public alias (no token) + the detailed endpoints
curl -s http://localhost:8000/api/v1/clusters/geojson | python3 -m json.tool | head
curl -s -H "Authorization: Bearer $TOKEN" \
  -X POST http://localhost:8000/api/v1/diagnoses \
  -F file=@data/samples/cmd_leaf.jpg -F latitude=0.3533 -F longitude=32.7553
```
