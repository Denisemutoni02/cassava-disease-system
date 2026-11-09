# ML pipeline — MobileNetV2 cassava leaf classifier

Trains, evaluates, quantises and exports a **three-class** cassava disease
classifier for server-side inference in the FastAPI backend:

| Class | Meaning |
|-------|---------|
| `Healthy` | No visible disease |
| `CMD` | Cassava Mosaic Disease |
| `CBSD` | Cassava Brown Streak Disease |

**Framework:** TensorFlow / Keras (MobileNetV2, ImageNet weights).
**Label order is fixed and alphabetical** — `["CBSD", "CMD", "Healthy"]` — and
matches `backend/app/services/classifier.py`. Do not reorder it.

---

## 1. Dataset structure

### Option A — flat class folders (recommended; script does the splitting)

```
data/cassava/
├── Healthy/  leaf001.jpg …
├── CMD/      leaf001.jpg …
└── CBSD/     leaf001.jpg …
```

Images: `.jpg/.jpeg/.png/.webp/.bmp`, any size (resised to 224×224).

### Option B — pre-split folders (used as-is)

```
data/cassava/
├── train/{Healthy,CMD,CBSD}/…
├── val/{Healthy,CMD,CBSD}/…
└── test/{Healthy,CMD,CBSD}/…      # optional
```

If `test/` is missing, a stratified **50% of `val/`** is held out as the test
set (printed warning; deterministic).

### Option C — CSV manifest

```csv
image_path,label
images/0001.jpg,CMD
images/0002.jpg,Healthy
/abs/path/0003.jpg,CBSD
```

Relative paths are resolved against the CSV's directory. Run with
`--csv path/to/manifest.csv`.

The loader prints the **class distribution** for train/val/test and **warns
when classes are imbalanced** (≥ 1.5:1) — balanced sample weights are then
applied automatically.

### Option D — download the public iCassava 2019 dataset (recommended)

No Kaggle account or API key needed:

```bat
cd /d E:\cassava-disease-system\ml
.venv\Scripts\python.exe prepare_public_dataset.py --per-class-cap 800
```

`prepare_public_dataset.py` downloads `cassavaleafdata.zip` (~1.26 GiB,
9430 real leaf photos) into `data\downloads\`, keeps only the three classes
the system needs (`cbsd→CBSD`, `cmd→CMD`, `healthy→Healthy`; bacterial blight
and green mottle are dropped) and writes a flat dataset to `data\cassava\`.
`--per-class-cap 0` keeps every image; `600–800` is a good balanced subset
for CPU training.

> No dataset at all? Generate a synthetic demo set in seconds:
> `python generate_synthetic_dataset.py --out ../data/synthetic --per-class 200`

---

## 2. Installation

**Windows (cmd — the project venv already exists at `ml\.venv`):**

```bat
cd /d E:\cassava-disease-system\ml
.venv\Scripts\pip.exe install -r requirements.txt
```

To create the venv from scratch (only if `.venv` is missing):

```bat
cd /d E:\cassava-disease-system\ml
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt
```

**Linux / macOS / WSL:**

```bash
cd ml
python -m venv .venv && source .venv/bin/activate    # Python 3.10–3.12
pip install -r requirements.txt
```

All commands below are written Unix-style; on Windows replace
`python` with `.venv\Scripts\python.exe` (or activate the venv first with
`.venv\Scripts\activate`).

---

## 3. Training

```bash
python train_mobilenetv2.py \
    --data ../data/cassava \
    --output-dir models/run \
    --epochs 10 --fine-tune-epochs 5 \
    --batch-size 32 --seed 42
```

Key arguments (all optional — defaults shown are the recommended first run):

| Flag | Default | Purpose |
|------|---------|---------|
| `--data` | `../data/synthetic` | Dataset root (layout auto-detected) |
| `--csv` | – | CSV manifest (overrides `--data` layout) |
| `--output-dir` | `models/run` | Where all artefacts are written |
| `--epochs` | `10` | Phase 1: head-only epochs |
| `--fine-tune-epochs` | `5` | Phase 2: backbone fine-tune epochs (`0` = skip) |
| `--batch-size` | `32` | Batch size |
| `--lr` | `1e-3` | Phase-1 Adam learning rate |
| `--fine-tune-lr` | `1e-5` | Phase-2 Adam learning rate |
| `--fine-tune-at` | `100` | Backbone layer index where fine-tuning starts (~last 30%) |
| `--patience` | `4` | Early-stopping patience on **val macro-F1** |
| `--val-split` / `--test-split` | `0.15` / `0.15` | Fractions for flat/CSV layouts |
| `--seed` | `42` | Full reproducibility (Python/NumPy/TF) |
| `--no-augment` | off | Disable augmentation |
| `--weights` | – | Start from an existing `.keras` checkpoint |

**What the script does**

1. Stratified train/val/test split → prints class distribution + imbalance warning.
2. Preprocessing: decode → resize 224×224 → scale to `[-1, 1]`.
3. Augmentation (train only): rotation ±29°, horizontal+vertical flip,
   brightness ±15%, contrast ±15%, zoom up to 10%.
4. **Phase 1** — freeze ImageNet backbone, train the new 3-class head (Adam 1e-3).
5. **Phase 2** — unfreeze from `--fine-tune-at` (BatchNorm stays frozen),
   fine-tune at 1e-5. Phase-1 weights are kept.
6. Metrics: accuracy each epoch; **macro-F1 computed on validation each epoch**
   (`val_macro_f1`) and used for **early stopping + best-model checkpointing**.
7. Final evaluation on the held-out **test set**: classification report
   (precision/recall/F1 macro + per-class) and confusion matrix.
8. Saves history and training-curve plots; writes the exact split manifests
   so quantisation/evaluation are repeatable.

### Saved files (`--output-dir`)

```
models/run/
├── best_model.keras            # best full-precision model (highest val macro-F1)
├── run_config.json             # every CLI argument + seed (reproducibility)
├── history.json                # per-epoch metrics incl. val_macro_f1
├── training_curves.png         # loss / accuracy / F1 plots
├── classification_report.txt   # test-set P/R/F1 report (human readable)
├── classification_report.json  # same, machine readable
├── confusion_matrix.png        # test-set confusion matrix
├── metrics.json                # headline test metrics
├── train_manifest.csv          # exact split used
├── val_manifest.csv
└── test_manifest.csv           # consumed by quantise.py
```

### Runs produced on this machine

| Output dir | Dataset | Test acc / macro-F1 |
|------------|---------|---------------------|
| `models/run_real/` | real iCassava subset (`..\data\cassava`, 2127 imgs) | **0.6332 / 0.6350** |
| `models/run/` | synthetic demo (`..\data\synthetic`, 600 imgs) | 0.9667 / 0.9662 |

The canonical deploy artefacts in `models\` (`mobilenetv2_cassava.onnx`,
`mobilenetv2_cassava_dynamic.tflite`, `quantisation_report.json`) were produced
from **`models/run_real/best_model.keras`** — the real-data model.

### Example output (verified on this machine)

**Real iCassava data** (`--per-class-cap 800`, 2127 images, 319 test images,
10 + 5 epochs, batch 32, seed 42, ~35 min on CPU):

```
===== TEST SET =====
              precision    recall  f1-score   support

        CBSD     0.6032    0.6333    0.6179       120
         CMD     0.7558    0.5417    0.6311       120
     Healthy     0.5701    0.7722    0.6559        79

    accuracy                         0.6332       319
   macro avg     0.6430    0.6491    0.6350       319

accuracy=0.6332  macro-F1=0.6350
```

Real field photography is hard — accuracy scales strongly with dataset size:
drop `--per-class-cap` (use all ~7000 images) and raise `--epochs 20
--fine-tune-epochs 8` for a materially better model (hours on CPU, minutes on
a GPU).

**Synthetic demo data** (600 train / 60 test, same settings, ~6 min):

```
        CBSD     0.9524    1.0000    0.9756        20
         CMD     1.0000    0.9000    0.9474        20
     Healthy     0.9524    1.0000    0.9756        20
    accuracy                         0.9667        60
   macro avg     0.9683    0.9667    0.9662        60
```

Synthetic patterns are easy — use them only to smoke-test the pipeline.

---

## 4. Quantisation

```bash
python quantise.py \
    --model models/run/best_model.keras \
    --test-manifest models/run/test_manifest.csv \
    --output-dir models \
    --onnx
```

| Flag | Effect |
|------|--------|
| *(default)* | TFLite **dynamic-range** quantisation (int8 weights) |
| `--full-int8` | TFLite **full-integer** (uint8 in/out; needs calibration images) |
| `--data-for-calibration <root>` | Calibration image source for `--full-int8` (defaults to test images) |
| `--onnx` | Also export ONNX via tf2onnx |
| `--no-eval` | Conversion only, skip test-set evaluation |

For every artefact the script measures **file size, test accuracy, macro/per-class
F1 and mean inference latency**, prints a comparison table and writes
`models/quantisation_report.json`.

### Example output (verified on this machine — real-data model)

```
==============================================================================
artefact             size MB    Δ size      acc       F1  latency ms
------------------------------------------------------------------------------
float                 24.403         —   0.6458   0.6464       181.8
tflite_dynamic         2.512    -89.7%   0.6426   0.6418       167.8
onnx                   8.942    -63.4%   0.6458   0.6464         9.7
==============================================================================
tflite_dynamic: Δacc -0.0031, ΔF1 -0.0047
onnx: Δacc +0.0000, ΔF1 +0.0000

Report written: models\quantisation_report.json
```

Quantisation shrinks the model **9×** (24.4 MB → 2.5 MB) for under half an F1
point. ONNX matches the float model exactly and is fastest to load and run —
that is what the backend uses (`backend/.env` → `MODEL_PATH=…onnx`).

*(Synthetic model comparison from the same machine: float 0.9833 acc →
tflite_dynamic 0.9500 → onnx 0.9833, same 24.4/2.5/8.9 MB sizes.)*

### Artefacts produced

```
models/
├── mobilenetv2_cassava_dynamic.tflite   # ~2.5 MB — primary deploy artefact
├── mobilenetv2_cassava_int8.tflite      # only with --full-int8 (~2.5 MB)
├── mobilenetv2_cassava.onnx             # only with --onnx (~9 MB)
└── quantisation_report.json
```

**Which format for FastAPI?**

- **TFLite (preferred)** — smallest; load with `tflite-runtime` (Py ≤ 3.11) or
  `tensorflow`.
- **ONNX** — load with `onnxruntime`; best choice on **Python 3.12+** where
  `tflite-runtime` wheels don't exist. The backend auto-detects the format
  from the file extension.

```env
# backend/.env   (project root also has a copy)
MODEL_PATH=E:\cassava-disease-system\ml\models\mobilenetv2_cassava.onnx
# or, with tensorflow/tflite-runtime installed:
# MODEL_PATH=E:\cassava-disease-system\ml\models\mobilenetv2_cassava_dynamic.tflite
```

---

## 5. Single-image prediction

```bash
python predict.py --image ../data/samples/cmd_leaf.jpg --pretty
python predict.py --image leaf.jpg --model models/mobilenetv2_cassava.onnx
```

Output (JSON on stdout; TF logs go to stderr, so piping is safe):

```json
{
  "label": "CMD",
  "confidence": 0.93,
  "all_probabilities": {"CBSD": 0.04, "CMD": 0.93, "Healthy": 0.03}
}
```

`--model` accepts `.tflite`, `.onnx` or `.keras`. When omitted it auto-detects
`models/mobilenetv2_cassava_dynamic.tflite` → `.tflite` → `.onnx` →
`models/run/best_model.keras`.

---

## 6. Recommended hyperparameters (first good run)

| Setting | Value | Rationale |
|---------|-------|-----------|
| epochs / fine-tune-epochs | **10 / 5** | Head converges fast; 5 fine-tune epochs usually suffice with patience 4 |
| batch-size | **32** (16 on CPU-only ≤4 GB RAM) | Stable batch norm-free training |
| lr | **1e-3** | Standard for a fresh softmax head |
| fine-tune-lr | **1e-5** | 100× lower — protects ImageNet features |
| fine-tune-at | **100** | ~last 30% of MobileNetV2 layers |
| patience | **4** on val macro-F1 | Robust to noisy small datasets |
| val/test split | **15% / 15%** each | Leaves 70% for training |
| augmentation | on | Rotation, flips, brightness, contrast, zoom |
| class balance | auto | Balanced sample weights when imbalance detected |

For **real field photos**: start from the synthetic-trained checkpoint with
`--weights models/run/best_model.keras` and fine-tune at `lr=1e-4` for a few
epochs (transfer from any related start beats ImageNet alone).

---

## 7. Script map

| File | Role |
|------|------|
| `common.py` | Shared constants (class order, IMG_SIZE), seeds, UTF-8 console setup, JSON helpers |
| `cassava_dataset.py` | Loading (folder/CSV), stratified split, augmentation, imbalance report |
| `train_mobilenetv2.py` | Two-phase transfer learning + evaluation + plots |
| `quantise.py` | PTQ → TFLite/ONNX + size/accuracy/latency comparison |
| `inference.py` | Shared Keras/TFLite/ONNX loader used by predict & quantise |
| `predict.py` | Single-image JSON prediction utility |
| `prepare_public_dataset.py` | Downloads iCassava 2019 (1.26 GiB) and maps it to the 3 classes |
| `generate_synthetic_dataset.py` | Demo data generator (no real photos needed) |
| `train.py` / `evaluate.py` / `export_tflite.py` / `export_onnx.py` | Earlier minimal pipeline (superseded by the scripts above) |
| `pipeline.sh` | One-shot demo: generate → train → quantise → evaluate |
| `run_pipeline.bat` | Windows one-shot: train → quantise → predict |

## 8. End-to-end checklist

**Windows (cmd, from `E:\cassava-disease-system\ml`):**

```bat
cd /d E:\cassava-disease-system\ml
.venv\Scripts\pip.exe install -r requirements.txt

REM 1. data — either the real public dataset (a few minutes) …
.venv\Scripts\python.exe prepare_public_dataset.py --per-class-cap 800
REM    … or the instant synthetic demo set
.venv\Scripts\python.exe generate_synthetic_dataset.py --out ..\data\synthetic --per-class 200

REM 2. train
.venv\Scripts\python.exe train_mobilenetv2.py --data ..\data\cassava --output-dir models\run

REM 3. quantise + compare (TFLite dynamic + ONNX)
.venv\Scripts\python.exe quantise.py --model models\run\best_model.keras ^
       --test-manifest models\run\test_manifest.csv --onnx

REM 4. sanity-check a photo
.venv\Scripts\python.exe predict.py --image ..\data\samples\cmd_leaf.jpg --pretty

REM 5. wire into FastAPI  (backend/.env already points at the ONNX model)
REM    MODEL_PATH=E:\cassava-disease-system\ml\models\mobilenetv2_cassava.onnx
REM    then restart the backend (start_backend.bat)
```

Or simply run the whole chain at once: `run_pipeline.bat`.

**Linux / macOS / WSL:** same steps with `python` after activating `.venv`.
