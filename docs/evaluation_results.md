# Evaluation results

**System:** Cassava Disease Detection (CassavaGuard) — MobileNetV2 · FastAPI · React PWA
**Date:** 2026-10-25
**Environment:** Windows 11, CPU-only inference (no GPU), SQLite database, live API on `127.0.0.1:8000`
**Deployed artefact:** `ml/models/mobilenetv2_cassava.onnx` (`onnx-mobilenetv2_cassava`)

All numbers below were produced by the scripts listed in
[Reproducing these numbers](#reproducing-these-numbers) on this machine.

---

## 1. What was measured

| Item | Choice |
|------|--------|
| Test set | `ml/models/run_real/test_manifest.csv` — **319 images**, the 15% split held out at training time (seed 42), never seen during training |
| Class balance | CBSD 120 · CMD 120 · Healthy 79 (natural imbalance of the source dataset) |
| Inference path | The **production** path (`backend/app/services/classifier.py`: PIL decode → 224×224 bilinear resize → `/127.5 - 1` → ONNX Runtime), i.e. exactly what `POST /diagnose` runs |
| Threshold | 0.60 (`CONFIDENCE_THRESHOLD`); below it the API returns label `Uncertain` + soft advice |
| Metrics | Accuracy, per-class precision/recall/F1, macro + weighted averages, confusion matrix, confidence distribution, latency, file sizes |

---

## 2. Classification metrics — deployed model, held-out test set

```
Images evaluated : 319   (CBSD 120, CMD 120, Healthy 79)
Accuracy         : 0.6458
Macro    P / R / F1 : 0.6540 / 0.6674 / 0.6464
Weighted P / R / F1 : 0.6679 / 0.6458 / 0.6447
```

### Per-class

| Class | Precision | Recall | F1 | Support |
|-------|----------:|-------:|----:|--------:|
| CBSD | 0.6535 | 0.5500 | 0.5973 | 120 |
| CMD | 0.7629 | 0.6167 | 0.6820 | 120 |
| Healthy | 0.5455 | 0.8354 | 0.6600 | 79 |
| **macro avg** | **0.6540** | **0.6674** | **0.6464** | 319 |
| **weighted avg** | **0.6679** | **0.6458** | **0.6447** | 319 |

### Confusion matrix (rows = true, cols = predicted)

|            | CBSD | CMD | Healthy |
|------------|-----:|----:|--------:|
| **CBSD**   | 66 | 19 | 35 |
| **CMD**    | 26 | 74 | 20 |
| **Healthy**| 9 | 4 | 66 |

**Reading the matrix.** The dominant error is *disease → Healthy* (35 CBSD and
20 CMD leaves called healthy), i.e. the model under-detects disease rather
than crying wolf. CMD is the most reliably detected disease (precision 0.76);
Healthy has the highest recall (0.84) but the lowest precision (0.55), so a
"healthy" verdict is the least trustworthy single prediction and should be
read together with the reported confidence.

### Cross-check against an independent implementation

These figures reproduce `ml/models/run_real/eval_deployed_onnx.json`
(`ml/evaluate_onnx.py`) and are numerically identical — to 4 decimal places —
to the independently written `ml/quantise.py` evaluation
(`models/quantisation_report.json`, accuracy 0.6458, per-class F1 0.5973 /
0.6820 / 0.6600). Two separate scripts, same manifest, same answers.

### Note on the training-time figure (0.6332)

`ml/models/run_real/metrics.json` reports **test accuracy 0.6332** for the
float Keras model. That number is produced by `train_mobilenetv2.py` through
the `tf.data` pipeline, which resizes with `tf.image.resize(bilinear)`;
production and `quantise.py` resize with `PIL.Image.resize(BILINEAR)`.
The two bilinear implementations differ slightly at image edges, flipping
**4 of 319** predictions (0.6332 → 0.6458). Both are legitimate; the
**0.6458 figure above is the one users of the deployed API actually
experience**, because it goes through the same code as `POST /diagnose`.

---

## 3. Confidence threshold and abstention behaviour

The risk engine abstains below `CONFIDENCE_THRESHOLD = 0.60` (label
`Uncertain`, soft advice). Measured over the same 319 test images:

| Threshold | Coverage (classified) | Abstained | Accuracy on classified | Overall correct* |
|----------:|----------------------:|----------:|-----------------------:|-----------------:|
| 0.50 | 75.5% | 78 | 0.6805 | 0.5141 |
| 0.55 | 63.3% | 117 | 0.7178 | 0.4545 |
| **0.60 (deployed)** | **54.9%** | **144** | **0.7371** | **0.4044** |
| 0.65 | 43.3% | 181 | 0.7536 | 0.3260 |
| 0.70 | 34.5% | 209 | 0.7909 | 0.2727 |

\* abstentions counted as incorrect (conservative view).

**At the deployed 0.60 threshold:**

- **54.9 %** of test images are given a disease/healthy verdict
- **45.1 %** come back `Uncertain` with photo-retaking advice
- when the system *does* answer, it is right **73.7 %** of the time
  (selective accuracy, vs. 64.6 % for unconditional argmax)

This is the intended safety trade-off for an agricultural advisory tool: it is
better to say *"retake the photo / ask an officer"* than to assert a wrong
disease. Report coverage and selective accuracy alongside plain accuracy.

### Confidence distribution (raw argmax, n = 319)

```
mean 0.6376   sd 0.1603   min 0.3436   max 0.9742   >= 0.60: 54.9 %
```

---

## 4. Latency

### Model inference only (single image, batch = 1, n = 319)

| Stage | Median | Mean | p95 |
|-------|-------:|-----:|----:|
| PIL decode + resize + normalise + ONNX Runtime | 17.8 ms (idle) / 30.6 ms (server running) | 18.4 – 31.8 ms | 22.8 – 45.8 ms |
| ONNX Runtime only (from `quantise.py`) | — | 9.72 ms | — |

*Two back-to-back runs of `evaluate_onnx.py` are quoted; the spread is machine
load (the demo backend was running for the second run), not measurement noise.
Either way inference is ≤ 50 ms on CPU.*

### End-to-end HTTP `POST /diagnose` (live server, 3 warm-ups + 20 timed runs)

| | Min | Median | Mean | p95 | Max |
|--|----:|-------:|-----:|----:|----:|
| Wall-clock (upload → JSON response) | 84 ms | **127 ms** | 127 ms | 155 ms | 158 ms |

- payload ≈ 54 KB JPEG (1280×960 source), includes auth, validation, file
  storage, DB write and the cluster-summary query
- all 20 runs returned `200`. A repeat run on a busier machine showed the tail
  reaching p95 386 ms / max 410 ms, coinciding with runs that trigger the
  background DBSCAN recompute (CMD/CBSD + GPS) contending for the event loop —
  it never blocks the response
- **the farmer waits ~0.13 s for a verdict** — far below human reaction time
  for the task

---

## 5. Model size and quantisation

| Artefact | File | Size | Δ vs float | Accuracy | Macro F1 | Latency (from `quantise.py`) |
|----------|------|-----:|-----------:|---------:|---------:|-----------------------------:|
| Float Keras (training output) | `ml/models/run_real/best_model.keras` | 24.40 MB | — | 0.6458 | 0.6464 | 181.8 ms |
| **ONNX, deployed** | `ml/models/mobilenetv2_cassava.onnx` | **8.94 MB** | **−63.4 %** | 0.6458 | 0.6464 | **9.7 ms** |
| TFLite dynamic-range (alternative) | `ml/models/mobilenetv2_cassava_dynamic.tflite` | 2.51 MB | −89.7 % | 0.6426 | 0.6418 | 167.8 ms |

- **ONNX conversion is lossless here** (same accuracy/F1 as float) while
  shrinking the file 2.7× and cutting latency ~18.7× versus the Keras model
- the TFLite variant is 3.6× smaller again with a 0.3 pp accuracy cost; it is
  shipped as an alternative for very constrained devices
- the deployed ONNX fits the project's "quantised MobileNetV2 on-device /
  edge" requirement (8.94 MB, CPU-only)

---

## 6. Functional test results

### Live end-to-end suite — `backend/scripts/smoke_test.py` → **36 / 36 passed**

| Area | Checks |
|------|--------|
| Health & classifier identity | `/health` 200, classifier `onnx` (not mock) |
| Register / login | register 201 + JWT, duplicate 409, login 200, wrong password 401 |
| Diagnosis flow | `/diagnose` 200, all 10 response fields, valid label, probabilities sum to 1, GPS echoed, `diagnosis_id` returned, `model_version` = onnx |
| Persistence | diagnosis visible in `/api/v1/history` and `/api/v1/diagnoses` |
| Hotspots / map | `/api/v1/hotspots` 200 `FeatureCollection` with ≥ 1 cluster; 401 without token; public `/clusters/geojson` 200 |
| Failure cases | invalid bytes 422, empty file 422, partial GPS 422, out-of-range GPS 422, missing GPS accepted, oversized 413, wrong content type 415, unauthenticated `/diagnose` 401, unauthenticated `/history` 401 |
| Low-confidence advice | advice softened below 0.60 ("Low confidence … preliminary … retake") |
| Latency | 5/5 warm runs 200 (46–67 ms in that batch) |

### Pytest suite → **53 / 53 passed** (`backend/tests/`)

Covers the API contract, auth, storage, risk engine, clustering, history and
hotspots with the mock classifier (deterministic, `FORCE_MOCK_MODEL=true`).

### Frontend

`npm run build` completes clean (PWA service worker generated); all pages and
auth modules compile on the dev server.

---

## 7. Basic usability notes

### Advice clarity — good

Advice is short, imperative and specific (quoted verbatim from the live API):

**CMD @ 0.86**
```
Cassava Mosaic Disease (CMD) detected with 86% confidence.
• Remove and burn infected plants to reduce inoculum.
• Use certified disease-free planting material (cuttings).
• Control whitefly vectors; avoid planting near infected fields.
• Report the case to your MuZARDI extension officer.
```

**Uncertain @ 0.52** (the abstention path)
```
We could not identify the disease with enough confidence (52%).
• Retake the photo in daylight, one leaf filling the frame.
• Avoid shadows and hold the camera steady.
• Ask a MuZARDI extension officer to verify this case.
```

- every message states the confidence, so the farmer can judge reliability
- advice is actionable *and* escalation-aware (extension officer, hotspot map)
- low-confidence results never look like a firm diagnosis — the wording
  ("preliminary", "retake the photo") matches the abstention behaviour
- severity wording (`Low` / `Moderate` / `High`) is shown as a colour-coded
  badge next to the label

**Weakness:** one-line headline + bullets is clear but static — the same CMD
case always yields the same four bullets (no dose/variety-stage nuance), and
"Healthy" advice cannot rule out early/latent infection visible only in later
stages.

### Map readability — good for the demo scale

- 3 clusters are visible in the seeded data (CMD High 35 cases r ≈ 1.6 km,
  CBSD Emerging 7 cases r ≈ 1.3 km, CMD Emerging 5 cases r ≈ 1.1 km) near the
  demo GPS coordinates in central Uganda
- **colour + text are paired** for accessibility: CMD `#e6550d`,
  CBSD `#a50f15`, Healthy `#31a354`, plus risk levels High `#d73027` /
  Emerging `#fc8d59` / Low `#fee090`
- circle radius encodes the DBSCAN extent in metres; marker size grows with
  case count; popups state disease, case count, risk level, radius, algorithm
  parameters and last update time
- filter chips (All / CMD / CBSD) and the user-location marker work

**Weakness:** at ~1 km radii, clusters can overlap when farmers are within a
few km of each other; no cluster time-slider is provided (clusters recompute
from a 90-day window).

---

## 8. Reproducing these numbers

```bat
REM 1. Classification metrics on the held-out test set (deployed ONNX)
cd /d E:\cassava-disease-system\ml
..\venv\Scripts\python.exe evaluate_onnx.py --json models\run_real\eval_deployed_onnx.json

REM 2. Abstention / threshold table
..\venv\Scripts\python.exe selective_stats.py

REM 3. End-to-end latency (backend must be running)
cd /d E:\cassava-disease-system\backend
..\venv\Scripts\python.exe scripts\latency_probe.py

REM 4. Functional test suite (backend must be running)
..\venv\Scripts\python.exe scripts\smoke_test.py

REM 5. Backend unit/API tests (mock classifier)
..\venv\Scripts\python.exe -m pytest tests -q

REM 6. Re-verify the demo/sample image predictions (rewrites manifest.json)
cd /d E:\cassava-disease-system\ml
..\venv\Scripts\python.exe build_demo_tray.py
```

Machine-readable outputs:
`ml/models/run_real/eval_deployed_onnx.json`,
`ml/models/run_real/test_predictions.json`,
`ml/models/quantisation_report.json`,
`data/demo/manifest.json`.

---

## 9. Summary for the report

| Metric | Result |
|--------|--------|
| Test accuracy (deployed ONNX, n = 319) | **64.6 %** |
| Macro F1 | **0.646** |
| Selective accuracy at 0.60 threshold | **73.7 %** (covers 54.9 % of images) |
| End-to-end diagnosis latency | **~127 ms** median (p95 155 ms) |
| Model size | **8.94 MB** (−63 % vs 24.40 MB float) |
| Inference speed-up vs Keras float | **~18.7×** |
| Functional tests | **36/36** live + **53/53** pytest |
| Seeded hotspot clusters for demo | **3** (2 CMD, 1 CBSD) |

### Remaining limitations (also in README)

1. **Online-only.** Auth, diagnosis persistence and the map need the backend;
   there is no offline login or offline diagnosis queue.
2. **Three classes only** (Healthy / CMD / CBSD) — bacterial blight, green
   mottle and other iCassava classes are out of scope.
3. **Moderate accuracy on a hard, fine-grained visual task** (64.6 %): the
   3-class problem is genuinely difficult on this dataset; the system
   compensates with abstention rather than over-confident answers.
4. **Abstains on ~45 % of inputs** at the 0.60 threshold — a deliberate
   precision-over-recall choice that can frustrate users who always want an
   answer; the threshold is a single `.env` knob.
5. **Class imbalance** (Healthy n = 79 vs 120) and
   **disease → healthy** being the dominant error mode: a "healthy" verdict
   should not be treated as a certificate.
6. **Synthetic-looking / in-the-wild images degrade results** — lighting,
   focus and leaf-in-frame guidance is advisory only; no image-quality gate.
7. **GPS optional**, so diagnoses without coordinates never contribute to
   hotspots; clustering needs ≥ 3 cases within 2 km / 90 days to show a
   circle, so a fresh install shows an empty map until enough cases exist.
8. **No user study.** Usability notes above are heuristic inspection, not
   measured farmer feedback.
