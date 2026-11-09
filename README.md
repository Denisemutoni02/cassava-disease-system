# CassavaGuard — Cassava Disease Detection System (Windows)

**Location:** `E:\cassava-disease-system\`

An online PWA for detecting cassava leaf diseases (CMD / CBSD / Healthy) using a quantised MobileNetV2 model, with GPS-tagged diagnoses and DBSCAN hotspot mapping for MuZARDI, Uganda.

> **Requires an active internet connection** for diagnosis (model inference) and map tile loading (Leaflet + OpenStreetMap).

**Docs:** [Setup](docs/SETUP.md) · [API](docs/API.md) · [Database](docs/DATABASE.md) · [Architecture](docs/ARCHITECTURE.md) · [**Evaluation results**](docs/evaluation_results.md) · [**Demo script**](docs/DEMO_SCRIPT.md)

---

## Start the system

Two terminals — each with a single script. Both scripts run automatic checks
first and tell you exactly what to install if something is missing.

### Terminal 1 — Backend (FastAPI)

```bat
cd /d E:\cassava-disease-system\backend
start-backend.bat
```

(or double-click `E:\cassava-disease-system\backend\start-backend.bat`)

The script checks, in order:

| Check | If it fails |
|-------|-------------|
| Python venv at `E:\cassava-disease-system\venv` | `py -3.12 -m venv venv` then `venv\Scripts\python.exe -m pip install -r backend\requirements.txt` |
| Required Python packages | `venv\Scripts\python.exe -m pip install -r backend\requirements.txt` |
| Database reachable (`backend\.env` → `DATABASE_URL`) | Start it (`docker compose up -d postgres`) or set `DATABASE_URL=sqlite+aiosqlite:///./cassava_guard.db` — see `docs\DATABASE.md` |
| Model file `ml\models\mobilenetv2_cassava.onnx` | Warning only — the API falls back to the mock classifier |
| Port 8000 free (or already serving) | `netstat -ano \| findstr :8000` then `taskkill /F /PID <PID>` |

Wait for: `Uvicorn running on http://127.0.0.1:8000`

Verify the backend any time:

```bat
curl http://127.0.0.1:8000/health
```

Expected: `{"status":"ok", ...}`

### Terminal 2 — Frontend (React Vite)

```bat
cd /d E:\cassava-disease-system\frontend
start-frontend.bat
```

(or double-click `E:\cassava-disease-system\frontend\start-frontend.bat`)

The script checks that Node.js/npm are on PATH and that `node_modules` exists
(if not: `npm install`), starts Vite on port **5173** (fixed — it fails loudly
if the port is taken), and opens the browser automatically.

Wait for: `Local: http://localhost:5173/`

### Open the App

**http://localhost:5173** opens automatically. Log in with a demo account
(below) — with the backend running, login succeeds against the real API.

> **Login errors mean what they say:**
> `Cannot reach server. Check that the backend is running.` → backend not
> started, wrong `VITE_API_URL` in `frontend\.env`, or CORS blocking the origin.
> `No internet connection.` → the device really has no network.
>
> To run the frontend from another device on your LAN, set
> `CORS_ORIGINS=*` in `backend\.env` (the frontend already listens on all
> interfaces), and point `frontend\.env` at this machine's IP, e.g.
> `VITE_API_URL=http://192.168.1.20:8000`.

> The root shortcuts `start_backend.bat` and `start_frontend.bat` do the same
> thing from `E:\cassava-disease-system\`.

---

## Demo Accounts

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@muzardi.ug` | `Admin@123` |
| Officer | `officer@muzardi.ug` | `Officer@123` |
| Farmer | `farmer1@example.com` | `Farmer@123` |

The PWA sign-in uses these when the backend is reachable; if the backend is
unreachable it offers a local **demo mode** escape hatch on the sign-in screen,
with data kept on this device. **Sign-in and registration are online-only** —
with no network the screen shows *"No internet connection."* instead of
logging you in. **Diagnosing, history and the hotspot map need a backend
account** — `/diagnose`, `/api/v1/history` and `/api/v1/hotspots` return `401`
without a JWT. Demo-mode users who try to diagnose see a **Log in** prompt
instead of being logged out.

---

## Demo walkthrough

A timed, click-by-click script for the supervisor / MuZARDI presentation lives
in **[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)** (~8 minutes). It lists the
exact expected output at every step, using the ready-made images in
`data/demo\`:

1. **Sign in** with `farmer1@example.com` / `Farmer@123` (show a wrong
   password first — inline 401 error).
2. **Diagnose `data\demo\demo_cmd_1.jpg`** with GPS → CMD, 96 % confidence,
   4 advice bullets and the *"1 hotspot cluster(s) within 5 km"* banner.
3. **Show the honest failure case** — `data\demo\demo_low_confidence.jpg`
   → **Uncertain, 34 %**, softened "retake the photo" advice.
4. **`/history`** → your runs, newest first. **`/map`** → the 3 seeded
   DBSCAN clusters with popups and CMD/CBSD filters.

Predictions for every demo image are recorded in `data\demo\manifest.json`
(regenerate with `ml\build_demo_tray.py`).

---

## Sign in & registration

Two dedicated screens (both mobile-first, with inline validation):

| Screen | URL | What it does |
|--------|-----|--------------|
| **Sign in** | `http://localhost:5173/login` | Email-or-phone + password, *Remember me*, **Sign in** button |
| **Register** | `http://localhost:5173/register` | Full name, email or phone, password + confirm, role (farmer / extension officer) → **Create account** |

**To test sign-in**

1. Open the app — logged out it lands on `/login` (if not, go to `/login`).
2. Enter a demo account from the table above (e.g. `farmer1@example.com` /
   `Farmer@123`), tick **Remember me**, press **Sign in**.
   - Success → you return to the upload screen with your name in the header.
     *Remember me* off = the session ends when you close the tab.
   - Wrong password → inline alert `Incorrect identifier or password.`
   - Backend stopped → `Cannot reach server. Check that the backend is
     running.` (plus an optional *Continue in demo mode* button).
   - No network → `No internet connection. Connect to Wi-Fi or mobile data to
     sign in.` (sign-in never works offline).
3. Empty fields, short identifiers or a malformed email are caught **before**
   any request — the message appears under the field and the button stays
   usable for the next attempt.

**To test registration**

1. On `/login`, click **Don't have an account? Register** (or open
   `/register` directly).
2. Fill in: full name (2+ chars), email **or** phone (e.g. `+256 772 000
   000`), password (6+ chars with letters **and** numbers) and confirm it,
   then choose the role — **Create account**.
3. You are **signed in automatically** and land on the upload screen; the new
   account works immediately for `/diagnose`, `/history` and the map.
4. Friendly errors to try:
   - mismatched passwords → `Passwords do not match.` (inline)
   - weak password → `Weak password — use at least 6 characters with letters
     and numbers.`
   - register the same phone/email twice →
     `An account with this phone number or email already exists.`
   - no network → `No internet connection. Registration needs Wi-Fi or mobile
     data.`

The same flow works over HTTP:

```bat
curl -X POST http://localhost:8000/api/v1/auth/register -H "Content-Type: application/json" -d "{\"full_name\":\"Test Farmer\",\"phone\":\"+256700000999\",\"password\":\"secret123\",\"role\":\"farmer\"}"
curl -X POST http://localhost:8000/api/v1/auth/login -H "Content-Type: application/json" -d "{\"identifier\":\"+256700000999\",\"password\":\"secret123\"}"
```

(Register returns `201` with a JWT — auto sign-in; a duplicate returns `409`,
a bad password `401`.)

---

## What's Inside

```
E:\cassava-disease-system\
├── backend\                  FastAPI + SQLAlchemy + JWT auth
│   ├── app\
│   │   ├── api\              REST endpoints (/diagnose + /api/v1/...)
│   │   ├── services\         Classifier, clustering, risk engine
│   │   └── models\           SQLAlchemy ORM
│   └── scripts\              init_db.py, seed.py
├── frontend\                 React + Vite PWA
│   └── src\
│       ├── pages\            Login, Register, Upload, Result, Map, History
│       └── components\       Leaflet map, offline banner, layout
├── ml\                       ML pipeline (training, quantisation, export)
│   ├── models\
│   │   ├── mobilenetv2_cassava.onnx              ← Active model (8.9 MB, real data)
│   │   ├── mobilenetv2_cassava_dynamic.tflite    ← Alternative (2.5 MB)
│   │   ├── run\              Training run artefacts (synthetic demo data)
│   │   └── run_real\         Training run artefacts (real iCassava data)
│   ├── train_mobilenetv2.py  Training script (2-phase transfer learning)
│   ├── quantise.py           Post-training quantisation + comparison report
│   ├── predict.py            Single-image JSON prediction
│   ├── prepare_public_dataset.py  Downloads the public iCassava dataset
│   └── run_pipeline.bat      One-shot train → quantise → predict
├── data\
│   ├── cassava\              Real 3-class dataset (Healthy / CMD / CBSD)
│   ├── downloads\            Public dataset archive (1.26 GiB)
│   └── samples\              Test leaf images (healthy, cmd, cbsd)
├── docs\                     API docs, setup guide, architecture
├── venv\                     Python virtual environment (Windows)
├── .env                      Environment configuration
├── start_backend.bat         Double-click to start backend
└── start_frontend.bat        Double-click to start frontend
```

---

## Database

The system runs on **SQLite** (no PostgreSQL installation needed) with the database file at `backend\cassava_guard.db`. This is pre-seeded with demo data including 3 hotspot clusters.

To use **PostgreSQL + PostGIS** instead (for production):
1. Install PostgreSQL from https://www.postgresql.org/download/windows/
2. Install PostGIS bundle during setup
3. Create database: `CREATE DATABASE cassava;`
4. Edit `.env`: `DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/cassava`
5. Apply schema: `psql -U user -d cassava -f backend/app/db/schema.sql`

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/diagnose` | **Diagnose + save** (JWT) — image → label + advice, persists to DB, refreshes hotspots, returns cluster summary |
| POST | `/api/v1/auth/register` | Create account |
| POST | `/api/v1/auth/login` | Get JWT token |
| GET | `/api/v1/auth/me` | Current user info |
| POST | `/api/v1/diagnoses` | Upload leaf image → diagnosis + advice (JWT, officer-style detail) |
| GET | `/api/v1/diagnoses` | List user's diagnoses (JWT) |
| GET | `/api/v1/history` | **My past diagnoses** (JWT, paginated) — feeds the History page |
| GET | `/api/v1/hotspots` | **DBSCAN hotspots as GeoJSON** (JWT) — feeds the Map page |
| GET | `/api/v1/clusters/geojson` | Same clusters, public (no auth) — handy for scripts |
| GET | `/api/v1/clusters` | Get hotspot clusters (DBSCAN) |
| GET | `/api/v1/farms` | List farms |
| GET | `/api/v1/admin/stats` | Admin dashboard stats |

Full API docs at **http://localhost:8000/docs** (Swagger UI) when backend is running.

### Smoke test

With both servers running (`start_backend.bat`, `start_frontend.bat`), verify
end to end in ~2 minutes:

1. **http://localhost:5173/** loads and the banner shows *"Backend connected"*
   (not *"Cannot reach server"*).
2. **Register or sign in** — `/login` for existing accounts, or open
   `/register` from the *"Don't have an account? Register"* link and create
   one (see *Sign in & registration* above). You land on the Upload page with
   your name in the header.
3. **Upload a leaf photo with GPS** on `/diagnose` → you get label,
   confidence, advice, and (if a cluster is near) a *"N hotspot cluster(s)
   within 5 km"* summary on the Result page.
4. **`curl http://localhost:8000/api/v1/history`** with
   `Authorization: Bearer <token>` → `total >= 1`, newest row matches the
   `diagnosis_id` from step 3. Without a token → `401`.
5. **Open `/map`** → Leaflet shows coloured cluster circles from
   `/api/v1/hotspots`; filter CMD/CBSD works.
6. **Open `/history`** → the saved diagnoses appear (server) alongside any
   device-only demo entries, and clicking a row shows the Result page.
7. **`curl http://localhost:8000/api/v1/hotspots`** (with token) →
   `{"type":"FeatureCollection","features":[...]}`.
8. **Stop the backend** → the banner flips to *"Cannot reach server"* and the
   History page falls back to device storage; restart it and Retry recovers.

Backend tests: `cd backend && ..\venv\Scripts\python.exe -m pytest tests -q`
(53 tests). Frontend build: `cd frontend && npm run build`.

---

## ML Model

- **Architecture:** MobileNetV2 (ImageNet weights) + custom 3-class head
- **Classes:** CBSD, CMD, Healthy (alphabetical order)
- **Active format:** ONNX (loaded via `onnxruntime`), 8.94 MB | TFLite dynamic-range also available at 2.5 MB
- **Training data:** public iCassava 2019 dataset (`data\cassava\`, 2127 images, 3 classes)
- **Verified metrics:** **64.6 % accuracy / 0.646 macro-F1** on the 319-image
  hold-out through the *deployed* ONNX path (63.3 % recorded at training time —
  the small gap is float-resize vs PIL-resize pre-processing; see
  [`docs/evaluation_results.md`](docs/evaluation_results.md) for the full
  per-class breakdown, confusion matrix and threshold analysis)
- **Latency:** ~10 ms pure inference, 18–32 ms including decode/resize (CPU)

Retrain or improve it (everything lives under `E:\cassava-disease-system\ml\`):

```bat
cd /d E:\cassava-disease-system\ml

REM one-shot: train -> quantise -> predict check
run_pipeline.bat

REM or step by step:
.venv\Scripts\python.exe prepare_public_dataset.py --per-class-cap 0
.venv\Scripts\python.exe train_mobilenetv2.py --data ..\data\cassava --output-dir models\run_real --epochs 20 --fine-tune-epochs 8
.venv\Scripts\python.exe quantise.py --model models\run_real\best_model.keras --test-manifest models\run_real\test_manifest.csv --onnx
.venv\Scripts\python.exe predict.py --image ..\data\samples\cmd_leaf.jpg --pretty
```

See `ml\README.md` for full training instructions, hyperparameters and the
quantisation comparison table.

---

## Evaluation & test suites

Everything below was re-run for the final report — numbers and methodology are
in **[`docs/evaluation_results.md`](docs/evaluation_results.md)**.

**1. Model evaluation (319-image hold-out, deployed ONNX path)** — no server needed:

```bat
cd /d E:\cassava-disease-system\ml
..\venv\Scripts\python.exe evaluate_onnx.py --json models\run_real\eval_deployed_onnx.json
..\venv\Scripts\python.exe selective_stats.py      :: abstention/threshold table
```

**2. Backend tests (53)**:

```bat
cd /d E:\cassava-disease-system\backend
..\venv\Scripts\python.exe -m pytest -q
```

**3. Live end-to-end checks (36)** — needs both servers running:

```bat
cd /d E:\cassava-disease-system\backend
..\venv\Scripts\python.exe scripts\smoke_test.py      :: health, auth, diagnose, history, hotspots, 4xx cases
..\venv\Scripts\python.exe scripts\latency_probe.py   :: N-run end-to-end latency
```

**4. Frontend build:**

```bat
cd /d E:\cassava-disease-system\frontend
npm run build
```

**5. Re-verify demo images** (rewrites `data\demo\manifest.json`):

```bat
cd /d E:\cassava-disease-system\ml
..\venv\Scripts\python.exe build_demo_tray.py
```

---

## Known limitations

Honest constraints of the current system — worth stating before being asked:

- **Three classes only** (CBSD, CMD, Healthy) — bacterial blight and other
  cassava diseases are out of scope; for them the model can only say
  *Healthy* or *Uncertain*.
- **64.6 % hold-out accuracy, not production-grade.** Below the 0.60
  confidence threshold the model abstains (*Uncertain*) on ~45 % of hold-out
  images; when it does answer it is right 73.7 % of the time. It is a triage
  aid for an extension officer, not an autonomous diagnosis.
- **Class imbalance** — the hold-out is 120 CBSD / 120 CMD / 79 Healthy;
  Healthy recall is high (83.5 %) but precision is low (54.6 %).
- **Sign-in and registration are online-only**; with no network the app shows
  an error rather than creating a local-only account (the demo-mode escape
  hatch appears only when the *server* is unreachable, not on dead Wi-Fi).
- **GPS is optional.** Diagnosis still works without it, but the case then
  does not feed the hotspot map and no cluster banner is shown.
- **Cluster data is seeded demo history** (70 diagnoses in Uganda) plus live
  additions; DBSCAN recomputes after each GPS-tagged positive case, so counts
  drift as you demonstrate.
- **No user study** — the advice wording was reviewed for correctness and
  tone, not yet validated in the field with farmers or officers.
- **TFLite edge build is unbenchmarked on-device** — the 2.5 MB model exists
  and is measured on desktop; no Android/iOS runtime is wired up yet.
- **Map tiles need internet** (OpenStreetMap); history and clusters already
  come from the local server.

---

## Troubleshooting

**"Port 8000 already in use"**
```bat
netstat -ano | findstr :8000
taskkill /F /PID <PID>
```

**"Module not found"**
```bat
cd /d E:\cassava-disease-system
venv\Scripts\pip.exe install -r backend\requirements.txt
```

**Model not loading**
Ensure `E:\cassava-disease-system\ml\models\mobilenetv2_cassava.onnx` exists. The backend will use a mock classifier if the model file is missing.

**Database reset**
```bat
cd /d E:\cassava-disease-system\backend
del cassava_guard.db
..\venv\Scripts\python.exe scripts\init_db.py
..\venv\Scripts\python.exe scripts\seed.py
```

---

## Requirements

- **Python 3.12+** (installed at `C:\Users\Hi TECH COMPS\AppData\Local\Programs\Python\Python312\`)
- **Node.js 18+** (installed at `C:\Program Files\nodejs\`)
- **Internet connection** (for map tiles and any cloud model updates)

---

## Support

For issues, check `docs\SETUP.md` and `docs\API.md` for detailed guides.
