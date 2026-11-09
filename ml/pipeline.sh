#!/usr/bin/env bash
# End-to-end demo pipeline on the synthetic dataset.
#   1. generate data  2. train MobileNetV2  3. quantise to TFLite  4. (optional) ONNX
set -euo pipefail
cd "$(dirname "$0")"

python generate_synthetic_dataset.py --out ../data/synthetic --per-class "${PER_CLASS:-240}"
python train.py --data-dir ../data/synthetic --epochs "${EPOCHS:-3}" --fine-tune-epochs "${FT_EPOCHS:-2}"
python export_tflite.py --model models/mobilenetv2_cassava.keras
python evaluate.py --model models/mobilenetv2_cassava.keras --data-dir ../data/synthetic/val

if [[ "${EXPORT_ONNX:-0}" == "1" ]]; then
  python export_onnx.py --model models/mobilenetv2_cassava.keras
fi

echo "Done. Deployed artefact: models/mobilenetv2_cassava.tflite"
