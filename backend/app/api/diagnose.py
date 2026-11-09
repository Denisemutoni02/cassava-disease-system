"""Integrated diagnosis endpoint: POST /diagnose.

The full online flow, authenticated with a JWT:

* image → quantised MobileNetV2 inference (loaded **once at startup** via the
  ``get_classifier()`` singleton, ``MODEL_PATH`` env var)
* Risk Logic Engine → final label + severity + farmer-facing advice
* persists image metadata, diagnosis, advice and GPS into PostgreSQL/PostGIS
* queues a background DBSCAN hotspot refresh for positive cases with GPS
* returns label, confidence, advice and the updated cluster summary

Preprocessing mirrors training exactly (224×224, scale to [-1, 1]).

Request: multipart form (``file`` + optional ``latitude`` / ``longitude``)
with an ``Authorization: Bearer <token>`` header.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from app.api.diagnoses import _get_or_create_model_version, _recompute_clusters_background
from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.models import Advice, Diagnosis, LeafImage
from app.schemas.diagnose import DiagnoseResponse
from app.services.classifier import get_classifier
from app.services.clustering import count_hotspots_near
from app.services.risk_engine import RiskEngine, load_rules_from_db
from app.services.storage import ImageValidationError, validate_and_store

logger = logging.getLogger(__name__)
router = APIRouter(tags=["diagnosis"])

# Plain ints: the HTTP_* enum aliases are renamed/deprecated across Starlette
# versions (UNPROCESSABLE_ENTITY -> UNPROCESSABLE_CONTENT, etc.).
HTTP_413, HTTP_415, HTTP_422, HTTP_500 = 413, 415, 422, 500

# Content types accepted in addition to settings.allowed_image_types
_LENIENT_TYPES = {"", "application/octet-stream", "binary/octet-stream"}

# PIL format name → storage content type (used when the client omitted one)
_PIL_FORMAT_CTYPE = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def _check_gps(latitude: float | None, longitude: float | None) -> None:
    """Both coordinates must be provided together and within valid ranges."""
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=HTTP_422,
            detail="Provide both latitude and longitude, or neither.",
        )
    if latitude is not None and not -90.0 <= latitude <= 90.0:
        raise HTTPException(
            status_code=HTTP_422,
            detail="latitude must be between -90 and 90.",
        )
    if longitude is not None and not -180.0 <= longitude <= 180.0:
        raise HTTPException(
            status_code=HTTP_422,
            detail="longitude must be between -180 and 180.",
        )


def _check_content_type(content_type: str | None) -> None:
    allowed = set(get_settings().allowed_image_type_list)
    ctype = (content_type or "").lower().split(";")[0].strip()
    if ctype in _LENIENT_TYPES or ctype in allowed:
        return
    raise HTTPException(
        status_code=HTTP_415,
        detail=(
            f"Unsupported content type '{ctype}'. "
            f"Upload a JPEG or PNG image ({', '.join(sorted(allowed))})."
        ),
    )


def _validate_image_bytes(data: bytes) -> str:
    """Reject empty or undecodable payloads; return the PIL format name."""
    if not data:
        raise HTTPException(
            status_code=HTTP_422,
            detail="Empty upload: no image data received.",
        )
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()  # force full decode, catches truncated files
            return img.format or "JPEG"
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=HTTP_422,
            detail="Invalid image: the file could not be decoded as JPEG/PNG.",
        ) from exc


@router.post(
    "/diagnose",
    response_model=DiagnoseResponse,
    status_code=200,
    summary="Diagnose a leaf photo, save it and refresh hotspots (JWT)",
    responses={
        401: {"description": "Missing or invalid JWT token"},
        413: {"description": "Image larger than MAX_UPLOAD_MB"},
        415: {"description": "Unsupported content type"},
        422: {"description": "Invalid image or GPS values"},
        500: {"description": "Model inference failed"},
    },
)
async def diagnose(
    background_tasks: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="Leaf photo (JPEG/PNG/WebP)")],
    latitude: Annotated[float | None, Form(description="GPS latitude (-90..90)")] = None,
    longitude: Annotated[float | None, Form(description="GPS longitude (-180..180)")] = None,
) -> DiagnoseResponse:
    """Run inference, persist the diagnosis and refresh hotspot clusters.

    1. Validates GPS values, content type, size and that the payload really
       decodes as an image.
    2. Stores the image under ``UPLOAD_DIR`` and writes image metadata,
       diagnosis and advice to PostgreSQL/PostGIS (SQLite in dev/tests).
    3. Runs the quantised MobileNetV2 model (loaded once at startup).
    4. Applies the Risk Logic Engine → final label + severity + advice.
    5. Queues a background DBSCAN recompute (positive cases with GPS) and
       returns the result plus a nearby-cluster summary.
    """
    settings = get_settings()

    # --- 1. Input validation -------------------------------------------
    _check_gps(latitude, longitude)
    _check_content_type(file.content_type)

    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=HTTP_413,
            detail=f"Image exceeds the {settings.max_upload_mb} MB upload limit.",
        )
    pil_format = _validate_image_bytes(data)

    # Storage content type: trust the header when it is allowed, otherwise
    # fall back to the format detected from the actual bytes (lenient types).
    ctype = (file.content_type or "").lower().split(";")[0].strip()
    store_ctype = ctype if ctype in settings.allowed_image_type_list else _PIL_FORMAT_CTYPE.get(
        pil_format, "image/jpeg"
    )

    # --- 2. Persist image metadata (file on disk + leaf_images row) -----
    try:
        stored_path = validate_and_store(data, store_ctype)
    except ImageValidationError as exc:
        raise HTTPException(status_code=HTTP_422, detail=str(exc)) from exc

    image = LeafImage(
        user_id=user.user_id,
        file_path=str(stored_path),
        latitude=latitude,
        longitude=longitude,
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql" and latitude is not None:
        from geoalchemy2.elements import WKTElement

        image.gps_location = WKTElement(f"POINT({longitude} {latitude})", srid=4326)
    db.add(image)
    await db.flush()

    # --- 3. Inference (model already resident in memory) ---------------
    classifier = get_classifier()
    started = time.perf_counter()
    try:
        prediction = classifier.predict(data)
    except Exception as exc:
        logger.exception("Model inference failed (%s)", classifier.version_tag)
        raise HTTPException(
            status_code=HTTP_500,
            detail="Model inference failed. Check the server logs and MODEL_PATH.",
        ) from exc
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    # --- 4. Risk engine → final label + severity + advice --------------
    rules = await load_rules_from_db(db)
    engine = RiskEngine(rules)
    risk = engine.evaluate(prediction.label, prediction.confidence, settings.confidence_threshold)

    # --- 5. Persist diagnosis + advice ---------------------------------
    model_version = await _get_or_create_model_version(
        db,
        tag=prediction.model_version,
        architecture="MobileNetV2" if prediction.mode != "mock" else "MockClassifier",
    )
    diagnosis = Diagnosis(
        image_id=image.image_id,
        model_version_id=model_version.model_version_id if model_version else None,
        disease_label=risk.final_label,
        confidence_score=round(prediction.confidence, 4),
    )
    db.add(diagnosis)
    await db.flush()

    advice = Advice(
        diagnosis_id=diagnosis.diagnosis_id,
        advice_text=risk.advice_text,
        severity_level=risk.severity_level,
    )
    db.add(advice)
    await db.flush()

    logger.info(
        "diagnose label=%s confidence=%.3f mode=%s model=%s user=%s gps=(%s, %s) "
        "bytes=%d type=%s %.1fms",
        risk.final_label,
        prediction.confidence,
        prediction.mode,
        prediction.model_version,
        user.user_id,
        latitude,
        longitude,
        len(data),
        file.content_type,
        elapsed_ms,
    )

    # Commit first so the background job never races this transaction.
    await db.commit()

    # --- 6. Background hotspot refresh (does not block the response) ---
    if risk.final_label in ("CMD", "CBSD") and latitude is not None:
        background_tasks.add_task(
            _recompute_clusters_background,
            settings.cluster_eps_m,
            settings.cluster_min_samples,
            settings.cluster_window_days,
        )

    # --- 7. Nearby cluster summary (sync, cheap) -----------------------
    nearby = 0
    hotspot_msg = None
    if latitude is not None and longitude is not None:
        nearby = await count_hotspots_near(db, latitude, longitude, radius_km=5.0)
        if nearby:
            hotspot_msg = f"{nearby} hotspot cluster(s) within 5 km of this location."

    probs = prediction.all_probabilities or {prediction.label: prediction.confidence}
    return DiagnoseResponse(
        label=risk.final_label,
        confidence=round(prediction.confidence, 4),
        advice=risk.advice_text,
        all_probabilities=probs,
        latitude=latitude,
        longitude=longitude,
        diagnosis_id=str(diagnosis.diagnosis_id),
        nearby_hotspots=nearby,
        hotspot_message=hotspot_msg,
        model_version=classifier.version_tag,
    )
