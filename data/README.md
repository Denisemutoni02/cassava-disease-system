# Data directory

Everything the ML pipeline needs lives under `E:\cassava-disease-system\data\`.

| Path | Purpose |
|------|---------|
| `samples/` | Three demo leaf JPEGs (healthy / CMD / CBSD) — handy for `POST /api/v1/diagnoses` and `ml\predict.py` checks. |
| `cassava/` | **Real dataset, 3 classes** (Healthy / CMD / CBSD) prepared by `ml\prepare_public_dataset.py` from the public iCassava 2019 collection. Flat class folders — the trainer splits it stratified. |
| `downloads/cassavaleafdata.zip` | The raw public archive (~1.26 GiB, 9430 images). Kept so the dataset can be rebuilt offline; delete to reclaim space. |
| `raw/` | Temporary extraction folder used by `prepare_public_dataset.py` (removed automatically unless `--keep-raw` is passed). |
| `synthetic/` | Created by `ml\generate_synthetic_dataset.py`. Instant demo dataset for smoke-testing the pipeline without downloads. |

## Rebuilding the real dataset

```bat
cd /d E:\cassava-disease-system\ml
.venv\Scripts\python.exe prepare_public_dataset.py --per-class-cap 800
```

The iCassava archive contains five disease classes; the prepare step keeps only
**cbsd → CBSD**, **cmd → CMD** and **healthy → Healthy** (the system classifies
exactly these three) and drops bacterial blight / green mottle.

No proprietary MuZARDI imagery is shipped with this repository.
