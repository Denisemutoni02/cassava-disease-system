# Detailed setup guide

Companion to the root [README](../README.md). Everything here is optional
reading — the quick start in the README is enough to get running.

## 1. Database (PostgreSQL + PostGIS)

```bash
# Create role + database
sudo -u postgres psql <<'SQL'
CREATE USER cassava WITH PASSWORD 'cassava';
CREATE DATABASE cassava OWNER cassava;
SQL

# Apply canonical schema (enums, tables, GiST spatial indexes)
psql -U cassava -h localhost -d cassava -f backend/app/db/schema.sql
```

Verify:

```sql
SELECT PostGIS_Version();
\d+ hotspot_clusters
```

### SQLite fallback (demo only)

```bash
export DATABASE_URL=sqlite+aiosqlite:///./dev.db
python scripts/init_db.py && python scripts/seed.py
```

Geography columns become TEXT; clustering uses the separate lat/lon float
columns, so the demo behaves the same. Do not use SQLite in production.

## 2. Backend environment

```bash
cd backend
cp .env.example .env
```

| Variable | Notes |
|----------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:5432/dbname` |
| `JWT_SECRET` | ≥ 32 random bytes, e.g. `openssl rand -hex 32` |
| `MODEL_PATH` | Path to `.tflite` or `.onnx`; missing file → mock classifier |
| `CONFIDENCE_THRESHOLD` | Below this the label becomes `Uncertain` (default 0.60) |
| `FORCE_MOCK_MODEL` | `true` forces mock mode (tests/demos) |
| `CLUSTER_EPS_M` / `CLUSTER_MIN_SAMPLES` | DBSCAN parameters (2000 m / 3) |
| `CLUSTER_WINDOW_DAYS` | How far back clustering looks (90) |
| `UPLOAD_DIR` | Where validated leaf photos are written |
| `CORS_ORIGINS` | Comma-separated list, e.g. `https://app.example.com` |

## 3. Model training & quantisation

See [ml/README.md](../ml/README.md). Short version:

```bash
cd ml && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash pipeline.sh
```

Artefact lands at `ml/models/mobilenetv2_cassava.tflite`. Backend loads it
once per worker at startup (`/health` shows the mode: `tflite` / `onnx` / `mock`).

TFLite runtime options:

```bash
pip install tflite-runtime      # recommended on Linux servers
# or
pip install tensorflow-cpu
```

ONNX fallback: `python ml/export_onnx.py` then `pip install onnxruntime`
and set `MODEL_PATH=../ml/models/mobilenetv2_cassava.onnx`.

## 4. Running the backend

```bash
cd backend && source .venv/bin/activate
python scripts/seed.py                    # optional demo data
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Production (2 workers behind Nginx):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
```

### Nginx reverse proxy + TLS (example)

```nginx
server {
    listen 80;
    server_name api.example.com;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl http2;
    server_name api.example.com;
    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    client_max_body_size 12M;   # > MAX_UPLOAD_MB

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }
}
```

Serve the frontend build (`frontend/dist/`) from the same or another host with
HTTPS; set `VITE_API_BASE=https://api.example.com/api/v1` at build time.

## 5. Running the frontend

```bash
cd frontend
npm install
npm run dev            # development, http://localhost:5173
npm run build          # production PWA → frontend/dist
npm run preview        # smoke-test the production build locally
```

## 6. Tests

```bash
cd backend
python -m pytest tests/ -q
```

Tests run against SQLite + the mock classifier (no PostgreSQL/TFLite required)
and cover: auth, `/diagnoses` validation & happy path, risk engine, DBSCAN
maths, GeoJSON shape and RBAC.

## 7. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Classifier: mock` in `/health` | `MODEL_PATH` wrong or TFLite runtime missing |
| `401` from every endpoint | Token expired — log in again; check `JWT_SECRET` consistency across workers |
| `422` on upload | Wrong MIME type, >8 MB, or <64×64 px — see `detail` |
| Map tiles blank | Device offline, or OSM blocked; cluster GeoJSON still loads from API |
| `CORS` errors | Add the frontend origin to `CORS_ORIGINS` |
| PostGIS errors at startup | `CREATE EXTENSION postgis;` as superuser, then re-run `schema.sql` |
| Clusters never appear | Need ≥3 confident CMD/CBSD diagnoses with GPS within `CLUSTER_EPS_M`; hit `POST /clusters/recompute` |
