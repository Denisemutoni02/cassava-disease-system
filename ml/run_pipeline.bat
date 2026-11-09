@echo off
REM ==========================================================================
REM  One-shot ML pipeline for E:\cassava-disease-system\ml
REM  train  ->  quantise (TFLite + ONNX)  ->  single-image prediction check
REM
REM  Usage:  run_pipeline.bat
REM          (run from anywhere; it switches to its own folder)
REM ==========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
    echo [info] ml\.venv not found, falling back to python on PATH
    set "PY=python"
)

REM ---- pick dataset -------------------------------------------------------
set DATA=..\data\cassava
if not exist "%DATA%" set DATA=..\data\synthetic
if not exist "%DATA%" (
    echo [error] no dataset found. Run first:
    echo         %PY% prepare_public_dataset.py --per-class-cap 800
    echo     or: %PY% generate_synthetic_dataset.py --out ..\data\synthetic --per-class 200
    exit /b 1
)
echo [1/3] training on %DATA%
"%PY%" train_mobilenetv2.py --data "%DATA%" --output-dir models\run || goto :failed

echo.
echo [2/3] quantising + comparing artefacts
"%PY%" quantise.py --model models\run\best_model.keras --test-manifest models\run\test_manifest.csv --output-dir models --onnx || goto :failed

echo.
echo [3/3] single-image prediction check
"%PY%" predict.py --image ..\data\samples\cmd_leaf.jpg --pretty || goto :failed

echo.
echo ============================================================
echo  Pipeline finished. Artefacts:
echo    models\run\best_model.keras
echo    models\mobilenetv2_cassava_dynamic.tflite
echo    models\mobilenetv2_cassava.onnx
echo    models\quantisation_report.json
echo ============================================================
exit /b 0

:failed
echo.
echo [error] pipeline failed — see messages above.
exit /b 1
