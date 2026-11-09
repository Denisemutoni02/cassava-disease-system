# CassavaGuard Backend (FastAPI)

REST API for the cassava disease detection system. This build step centres on the
**standalone diagnosis endpoint** — upload a leaf photo, get back a label,
confidence, rule-based advice, per-class probabilities and GPS echo.

No authentication, no database and no clustering is required for `/diagnose`.

---

## Requirements

- Python 3.10 – 3.13 (venv lives at `E:\cassava-disease-system\venv`)
- Model artefact: `E:\cassava-disease-system\ml\models\mobilenetv2_cassava.onnx` (quantised MobileNetV2, 8.9 MB)

## Install

```cmd
cd /d E:\cassava-disease-system\backend
..\venv\Scripts\pip.exe install -r requirements.txt
```

## Run

```cmd
cd /d E:\cassava-disease-system
start_backend.bat
```

or directly:

```cmd
cd /d E:\cassava-disease-system\backend
..\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The model is loaded **once at startup** (lifespan hook); the first request then
runs in ~10–30 ms. Check it loaded:

```cmd
curl http://127.0.0.1:8000/health
```

```json
{"status":"ok","classifier":"onnx","model_version":"onnx-mobilenetv2_cassava","online_required":true}
```

If `classifier` says `mock`, the model file was not found — check `MODEL_PATH`
in `backend\.env`.

Interactive API docs: **http://localhost:8000/docs**

## Configuration (`backend\.env`)

Copy `.env.example` to `.env` (already done in this workspace) and adjust:

| Variable | Meaning | Default |
|----------|---------|---------|
| `MODEL_PATH` | Quantised model (.onnx or .tflite); missing file → mock classifier | `ml\models\mobilenetv2_cassava.onnx` |
| `CONFIDENCE_THRESHOLD` | Below this the full app labels results "Uncertain" | `0.60` |
| `FORCE_MOCK_MODEL` | `true` forces the deterministic mock (used by tests) | `false` |
| `MAX_UPLOAD_MB` | Upload size limit → HTTP 413 above it | `8` |
| `ALLOWED_IMAGE_TYPES` | Content types → HTTP 415 otherwise | `image/jpeg,image/png,image/webp` |

Environment variables override `.env`; `.env` overrides the code defaults.

---

## POST /diagnose

`multipart/form-data`:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `file` | file | yes | JPEG / PNG / WebP leaf photo |
| `latitude` | number | no | −90..90; must be sent together with `longitude` |
| `longitude` | number | no | −180..180 |

### cURL (Windows cmd)

```cmd
curl -X POST http://127.0.0.1:8000/diagnose ^
  -F "file=@E:\cassava-disease-system\data\samples\cmd_leaf.jpg;type=image/jpeg" ^
  -F "latitude=0.35" ^
  -F "longitude=32.75"
```

Omit the two `-F` GPS flags if the photo has no location.

### cURL (WSL)

Windows-bound localhost is not reachable from WSL — call Windows `curl.exe`:

```bash
/mnt/c/Windows/System32/curl.exe -X POST http://127.0.0.1:8000/diagnose \
  -F "file=@E:\cassava-disease-system\data\samples\cmd_leaf.jpg;type=image/jpeg" \
  -F "latitude=0.35" -F "longitude=32.75"
```

### Postman

1. Method **POST**, URL `http://127.0.0.1:8000/diagnose`
2. Body → **form-data**; add key `file`, change its type to **File**, pick the JPEG
3. Add keys `latitude` and `longitude` as Text with numeric values (or skip both)
4. Send — no Authorization header or setup script needed

### Response (200)

```json
{
  "label": "Healthy",
  "confidence": 0.4703,
  "advice": "Low confidence (47%) - this leaf may be Healthy, but treat it as a preliminary result. This leaf looks healthy. Keep scouting every 1-2 weeks, use only certified disease-free cuttings, and remove infected volunteers to keep your field this way. Retake the photo in good daylight (one leaf filling the frame, no shadows) and submit again for a more reliable answer.",
  "all_probabilities": {"CBSD": 0.1006, "CMD": 0.4291, "Healthy": 0.4703},
  "latitude": 0.35,
  "longitude": 32.75
}
```

- `label` ∈ `Healthy`, `CMD`, `CBSD`
- `advice` is rule-based: when confidence < **0.70** it is prefixed with a
  low-confidence warning and a "retake the photo" hint
- `all_probabilities` sums to 1 (same class order as training: CBSD, CMD, Healthy)

### Error codes

| Code | Cause | Example `detail` |
|------|-------|------------------|
| 413 | Image larger than `MAX_UPLOAD_MB` | `Image exceeds the 8 MB upload limit.` |
| 415 | Wrong content type | `Unsupported content type 'application/pdf'. ...` |
| 422 | Undecodable/empty file | `Invalid image: the file could not be decoded as JPEG/PNG.` |
| 422 | GPS incomplete or out of range | `Provide both latitude and longitude, or neither.` |
| 500 | Inference failed (bad `MODEL_PATH`, corrupt model) | `Model inference failed. Check the server logs and MODEL_PATH.` |

Every request logs one line (label, confidence, model, GPS, size, latency)
without storing the image:

```
INFO app.api.diagnose: diagnose label=Healthy confidence=0.470 mode=onnx
model=onnx-mobilenetv2_cassava gps=(0.35, 32.75) bytes=9397 type=image/jpeg 16.1ms
```

---

## Tests

```cmd
cd /d E:\cassava-disease-system\backend
..\venv\Scripts\python.exe -m pytest -q
```

Tests run with `FORCE_MOCK_MODEL=true` (deterministic, no model file needed):
`tests\test_diagnose_endpoint.py` covers `/diagnose` (contract, GPS, size,
type, decode, advice rules); the remaining files cover the authenticated
`/api/v1/*` endpoints used by later steps.

## Other endpoints

`/api/v1/auth/*`, `/api/v1/diagnoses`, `/api/v1/clusters`, `/api/v1/farms`,
`/api/v1/admin/stats` exist for the full app (JWT + database) and are not used
by `/diagnose`. See the root `README.md` for the complete table.
