# Demo script — CassavaGuard

A click-by-click walkthrough for the supervisor / MuZARDI demonstration.
Total ≈ 8 minutes. Every "expected" output below was verified live against the
running system (`backend/scripts/smoke_test.py` → 36/36 passed).

**Sample images** live in `data/demo/` (10 images) — predictions for each are
recorded in `data/demo/manifest.json`.

---

## 0. Before the audience arrives (~2 min)

**Start the system** (two terminals, or double-click the two root `.bat` files):

```bat
E:\cassava-disease-system\start_backend.bat     :: runs preflight, then uvicorn :8000
E:\cassava-disease-system\start_frontend.bat    :: checks node_modules, runs Vite, opens browser
```

* Preflight prints `[ OK ]` on every line. If it says *"already running … not
  starting a second one"* that is **success, not an error** (exit code 2 — a
  healthy instance already owns the port). Exit code 1 = a real problem;
  the output names the exact fix.
* Confirm the API: <http://127.0.0.1:8000/health> →
  `{"status":"ok","classifier":"onnx","model_version":"onnx-mobilenetv2_cassava",…}`
* Open <http://localhost:5173> — it redirects to `/login`.

**Optional (recommended) — fake the GPS** so the hotspot banner works on any
laptop: Chrome DevTools (F12) → `⋮` → *More tools* → *Sensors* →
*Location* → *Manage* → add custom **latitude 0.353, longitude 32.756**
(the seeded cluster area in Uganda). Now "📍 Use my GPS location" lands in the
field. Without this step everything else still works; only the banner and the
"your location" marker are affected.

**Demo account:** `farmer1@example.com` / `Farmer@123`
(other seeded accounts: see README → *Sign in & registration*).

---

## 1. Sign in (≈1 min)

1. On `/login`, deliberately type a wrong password first → inline red alert:
   **"Incorrect identifier or password."** (401 handled, no crash, no reload).
2. Log in properly (`farmer1@example.com` / `Farmer@123`) → lands on
   **/diagnose**.
3. Talking points:
   - tabbed Sign in / Register UI, live field validation, Show/Hide password.
   - *Remember me* → token in `localStorage` (survives refresh);
     without it → `sessionStorage` (cleared on close).
   - **Register** tab works too: creating an account signs you straight in
     (confirmation flash → `/diagnose`), duplicate email → "already exists".

## 2. Upload & diagnose (≈2 min)

1. On `/diagnose` (**New diagnosis**), click the dropzone —
   *"📷 Tap to take a photo or choose from gallery"* — and pick
   **`data/demo/demo_cmd_1.jpg`**.
2. Click **"📍 Use my GPS location"** → the row turns into
   `Location detected ✓ (0.3530, 32.7560)`.
3. Click **"Submit for diagnosis"** (shows *Analysing…*) → `/result` shows:

| Element | Expected |
|---|---|
| Heading | 🍂 **Cassava Mosaic Disease (CMD)** |
| Badge / confidence | `CMD` · **Confidence 96%** (raw 0.9645) |
| GPS chip | 📍 0.3530, 32.7560 |
| Hotspot banner | 🗺️ **"1 hotspot cluster(s) within 5 km of this location."** + *View the hotspot map* |
| Risk advice | 4 bullets: remove & burn infected plants · certified cuttings · control whitefly vectors · report to MuZARDI officer |
| Model scores | CMD 96.5 % · CBSD 2.8 % · Healthy 0.8 % |

4. Talking points: mobile-first leaf photo in → advice out; runs the quantised
   **ONNX MobileNetV2** (`onnx-mobilenetv2_cassava`), 8.94 MB, ~18–32 ms
   inference; the row is saved to the DB and a background DBSCAN refresh runs
   for GPS-tagged positive cases.

## 3. The honest failure case (≈1.5 min)

1. Upload **`data/demo/demo_low_confidence.jpg`**, *no* GPS (leave the GPS
   button untouched) → **Submit for diagnosis**.

| Element | Expected |
|---|---|
| Heading | 🍂 **Uncertain** (amber "warn" card styling) |
| Confidence | **34%** |
| Advice (softened) | "We could not identify the disease with enough confidence (34%)." → retake the photo in daylight · avoid shadows · ask a MuZARDI extension officer |
| Scores | CMD 34.5 % · CBSD 31.9 % · Healthy 33.6 % (all close) |

2. Talking points — this is the system knowing what it does not know:
   - confidence threshold **0.60**: below it the model *abstains* and hands
     over to a human instead of guessing.
   - on the 319-image hold-out that abstains on **45 %** of images, and when it
     does answer it is right **73.7 %** of the time (vs 64.6 % overall).
   - full numbers: [`docs/evaluation_results.md`](evaluation_results.md).

## 4. History (≈30 s)

1. Go to **/history** → newest first; your two runs from beats 2–3 are at the
   top, above the earlier seeded rows.
2. Talking points: server-side history (`GET /api/v1/history`, JWT, paginated)
   merged with anything cached locally; each row shows label, confidence and
   the advice text; filterable by label.

## 5. Outbreak map (≈1 min)

1. Open **/map** (or the *View the hotspot map* link from the banner) →

| Cluster (current seed) | Circle colour | Members | Radius |
|---|---|---:|---:|
| CMD · High risk | orange `#e6550d` (CMD) | n ≈ 58 | ~1.6 km |
| CBSD · Emerging | dark red `#a50f15` (CBSD) | n ≈ 7 | ~1.3 km |
| CMD · Emerging | orange `#e6550d` (CMD) | n ≈ 5 | ~1.1 km |

*Circle colour = dominant disease; risk level (High `#d73027`, Emerging
`#fc8d59`, Low `#fee090`) appears in the popup text and the legend.*

2. Click a circle → popup with disease, risk level, member count, radius,
   algorithm (`DBSCAN`, **eps 2 km, min_samples 3**).
   Use the **All / CMD / CBSD** filter chips above the map to narrow the view.
3. Talking points:
   - **DBSCAN** over confident CMD/CBSD diagnoses with GPS; isolated single
     cases never form a hotspot.
   - Clusters refresh in the background after every GPS diagnosis — the counts
     above *grow as you demo*, which is the feature working, not a bug.
   - Counts + radii are live from `GET /api/v1/clusters/geojson` (public) and
     `GET /api/v1/hotspots` (JWT).

## 6. Optional: error handling (≈30 s)

Pick one:
- **Bad upload** — submit a `.txt` file → clean inline error (415/422), the
  page never white-screens.
- **Server down** — stop the backend window → the upload page shows
  "Cannot reach server…" with a **Retry** button and the offline banner; restart
  the backend and hit Retry.
- **Auth guard** — log out and try `/diagnose` directly → redirected to
  `/login`; an expired/absent token on the API returns 401 with a
  "Please log in…" prompt.

---

## Numbers worth quoting

| Claim | Value | Source |
|---|---|---|
| Accuracy (hold-out, 319 images) | **64.6 %** (macro F1 0.646) | `docs/evaluation_results.md` |
| Per-class F1 | CBSD 0.60 · CMD 0.68 · Healthy 0.66 | same |
| Abstention @ 0.60 | 45 % abstain → 73.7 % selective accuracy | same |
| Deployed model size | **8.94 MB** ONNX (−63 % vs 24.40 MB Keras) | `ml/models/quantisation_report.json` |
| Inference latency | 18–32 ms CPU (pure ONNX 9.7 ms) | `docs/evaluation_results.md` |
| End-to-end HTTP | median **127 ms**, p95 155 ms (n=20) | same |
| Functional test suite | **36/36** checks | `backend/scripts/smoke_test.py` |
| Backend test suite | **53/53** tests | `backend` → `pytest -q` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Preflight exit 1, port busy by another service | `netstat -ano \| findstr :8000` then `taskkill /F /PID <PID>` |
| Preflight says "already running" | Success (exit 2) — open http://localhost:5173 |
| `[WARN] Model file not found` | Fix `MODEL_PATH` in `backend\.env`, or the API falls back to the mock classifier (say so if asked!) |
| Browser can't reach API | Check `.env` `CORS_ORIGINS` includes `http://localhost:5173` |
| Geolocation denied | Continue without GPS, or use DevTools → Sensors (step 0) |
| Frontend on wrong port / stale build | Ctrl+C the Vite window, re-run `start_frontend.bat` |
| Reset the demo DB | see README → *Troubleshooting* → "Database reset" (then `ml\build_demo_tray.py`) |

## Re-verify before presenting

```bat
:: 36/36 end-to-end checks against the running server
cd /d E:\cassava-disease-system\backend
..\venv\Scripts\python.exe scripts\smoke_test.py

:: 53/53 unit/API tests
..\venv\Scripts\python.exe -m pytest -q

:: re-check sample/demo image predictions (also rewrites manifest.json)
cd /d E:\cassava-disease-system\ml
..\venv\Scripts\python.exe build_demo_tray.py
```
