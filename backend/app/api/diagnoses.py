"""Diagnosis endpoints.

POST /diagnoses is the core flow:
  upload image + optional GPS → CNN inference → risk advice →
  persist diagnosis → queue background hotspot recompute → return result.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.deps import CurrentUser, DbSession, StaffUser
from app.models import Advice, Diagnosis, Farm, LeafImage, ModelVersion
from app.schemas.diagnosis import (
    AdviceOut,
    DiagnosisCreateResponse,
    DiagnosisOut,
    DiagnosisPage,
)
from app.services.classifier import get_classifier
from app.services.clustering import (
    count_hotspots_near,
    haversine_km,
    recompute_clusters,
)
from app.services.risk_engine import RiskEngine, load_rules_from_db
from app.services.storage import ImageValidationError, validate_and_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/diagnoses", tags=["diagnoses"])


def _diagnosis_to_out(d: Diagnosis, image: LeafImage) -> DiagnosisOut:
    return DiagnosisOut(
        diagnosis_id=d.diagnosis_id,
        image_id=d.image_id,
        disease_label=d.disease_label,
        confidence_score=d.confidence_score,
        inferred_at=d.inferred_at,
        latitude=image.latitude,
        longitude=image.longitude,
        advice=AdviceOut.model_validate(d.advice) if d.advice else None,
    )


async def _get_or_create_model_version(db, tag: str, architecture: str) -> ModelVersion | None:
    """Register the model artefact used for this prediction (idempotent)."""
    existing = (
        await db.execute(select(ModelVersion).where(ModelVersion.version_tag == tag))
    ).scalar_one_or_none()
    if existing:
        return existing
    mv = ModelVersion(version_tag=tag, architecture=architecture, is_active=True)
    db.add(mv)
    await db.flush()
    return mv


async def _recompute_clusters_background(eps_m: float, min_samples: int, window_days: int) -> None:
    """Run DBSCAN in a fresh session after the response is sent."""
    from app.db import SessionLocal

    async with SessionLocal() as db:
        try:
            await recompute_clusters(db, eps_m=eps_m, min_samples=min_samples, window_days=window_days)
            await db.commit()
        except Exception:
            logger.exception("Background cluster recompute failed")
            await db.rollback()


@router.post(
    "",
    response_model=DiagnosisCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a leaf photo and run CNN diagnosis",
)
async def create_diagnosis(
    background_tasks: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="Leaf photo (JPEG/PNG/WebP, max 8 MB)")],
    farm_id: Annotated[str | None, Form()] = None,
    latitude: Annotated[float | None, Form(description="GPS latitude (-90..90)")] = None,
    longitude: Annotated[float | None, Form(description="GPS longitude (-180..180)")] = None,
    gps_accuracy_m: Annotated[float | None, Form(description="GPS accuracy in metres")] = None,
    captured_at: Annotated[str | None, Form(description="ISO-8601 capture time")] = None,
) -> DiagnosisCreateResponse:
    """Full online diagnosis flow (internet required).

    1. Validates the image (type, size, resolution).
    2. Runs the quantised MobileNetV2 classifier (server-side).
    3. Applies the Risk Logic Engine → final label + severity + advice.
    4. Saves image, diagnosis and advice; queues a DBSCAN hotspot update.
    5. Returns the result plus a nearby-hotspot summary.
    """
    settings = get_settings()

    # --- Validate GPS inputs (optional but must be consistent) ---
    if latitude is not None and longitude is None or longitude is not None and latitude is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide both latitude and longitude, or neither.",
        )
    if latitude is not None and not (-90 <= latitude <= 90):
        raise HTTPException(status_code=422, detail="Latitude must be between -90 and 90.")
    if longitude is not None and not (-180 <= longitude <= 180):
        raise HTTPException(status_code=422, detail="Longitude must be between -180 and 180.")

    # Optional farm ownership check
    if farm_id:
        farm = (
            await db.execute(select(Farm).where(Farm.farm_id == farm_id, Farm.user_id == user.user_id))
        ).scalar_one_or_none()
        if farm is None:
            raise HTTPException(status_code=404, detail="Farm not found for this user.")
        if latitude is None and farm.latitude is not None:
            latitude, longitude = farm.latitude, farm.longitude

    # --- 1. Validate + store image ---
    raw = await file.read()
    try:
        stored_path = validate_and_store(raw, file.content_type or "application/octet-stream")
    except ImageValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    captured_dt: datetime | None = None
    if captured_at:
        try:
            captured_dt = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="captured_at must be ISO-8601.")

    image = LeafImage(
        user_id=user.user_id,
        farm_id=farm_id,
        file_path=str(stored_path),
        latitude=latitude,
        longitude=longitude,
        gps_accuracy_m=gps_accuracy_m,
        captured_at=captured_dt,
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql" and latitude is not None:
        from geoalchemy2.elements import WKTElement

        image.gps_location = WKTElement(f"POINT({longitude} {latitude})", srid=4326)

    db.add(image)
    await db.flush()

    # --- 2. CNN inference (server-side only) ---
    classifier = get_classifier()
    prediction = classifier.predict(raw)

    # --- 3. Risk engine ---
    rules = await load_rules_from_db(db)
    engine = RiskEngine(rules)
    risk = engine.evaluate(prediction.label, prediction.confidence, settings.confidence_threshold)

    # --- 4. Persist diagnosis + advice ---
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
    diagnosis.advice = advice

    # --- 5. Background hotspot refresh (does not block the response) ---
    # Commit first so the background job never races this request's transaction.
    await db.commit()
    if risk.final_label in ("CMD", "CBSD") and latitude is not None:
        background_tasks.add_task(
            _recompute_clusters_background,
            settings.cluster_eps_m,
            settings.cluster_min_samples,
            settings.cluster_window_days,
        )

    # --- Nearby hotspot summary (sync, cheap) ---
    nearby = 0
    hotspot_msg = None
    if latitude is not None and longitude is not None:
        nearby = await count_hotspots_near(db, latitude, longitude, radius_km=5.0)
        if nearby:
            hotspot_msg = f"{nearby} hotspot cluster(s) within 5 km of this location."

    return DiagnosisCreateResponse(
        diagnosis=_diagnosis_to_out(diagnosis, image),
        nearby_hotspots=nearby,
        hotspot_message=hotspot_msg,
        model_version=classifier.version_tag,
    )


@router.get("", response_model=DiagnosisPage, summary="Diagnosis history (mine, or all for staff)")
async def list_diagnoses(
    db: DbSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    scope: Annotated[str, Query(pattern="^(mine|all)$")] = "mine",
    label: Annotated[str | None, Query(pattern="^(CMD|CBSD|Healthy|Uncertain)$")] = None,
) -> DiagnosisPage:
    """Paginated history. Officers/admins may pass ``scope=all``."""
    base = (
        select(Diagnosis)
        .join(LeafImage, Diagnosis.image_id == LeafImage.image_id)
        .options(selectinload(Diagnosis.advice))
    )
    if scope == "all" and user.role not in ("officer", "admin"):
        raise HTTPException(status_code=403, detail="Only officers/admins may view all diagnoses.")
    if scope == "mine":
        base = base.where(LeafImage.user_id == user.user_id)
    if label:
        base = base.where(Diagnosis.disease_label == label)

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(Diagnosis.inferred_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()

    items = []
    for d in rows:
        image = (
            await db.execute(select(LeafImage).where(LeafImage.image_id == d.image_id))
        ).scalar_one()
        items.append(_diagnosis_to_out(d, image))

    return DiagnosisPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{diagnosis_id}", response_model=DiagnosisOut, summary="Get one diagnosis")
async def get_diagnosis(diagnosis_id: str, db: DbSession, user: CurrentUser) -> DiagnosisOut:
    d = (
        await db.execute(
            select(Diagnosis)
            .where(Diagnosis.diagnosis_id == diagnosis_id)
            .options(selectinload(Diagnosis.advice))
        )
    ).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Diagnosis not found.")
    image = (await db.execute(select(LeafImage).where(LeafImage.image_id == d.image_id))).scalar_one()
    # Access control: own diagnoses, or staff
    if image.user_id != user.user_id and user.role not in ("officer", "admin"):
        raise HTTPException(status_code=403, detail="Not allowed to view this diagnosis.")
    return _diagnosis_to_out(d, image)


@router.post(
    "/{diagnosis_id}/verify",
    response_model=DiagnosisOut,
    summary="Officer verification of a diagnosis (feedback)",
)
async def verify_diagnosis(
    diagnosis_id: str,
    db: DbSession,
    user: StaffUser,
    verified_label: Annotated[str, Query(pattern="^(CMD|CBSD|Healthy|Uncertain)$")],
    comments: Annotated[str | None, Query(max_length=1000)] = None,
) -> DiagnosisOut:
    """Attach officer feedback (used for model monitoring / retraining)."""
    from app.models import DiagnosisFeedback

    d = (
        await db.execute(
            select(Diagnosis)
            .where(Diagnosis.diagnosis_id == diagnosis_id)
            .options(selectinload(Diagnosis.advice))
        )
    ).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Diagnosis not found.")

    db.add(
        DiagnosisFeedback(
            diagnosis_id=d.diagnosis_id,
            officer_id=user.user_id,
            verified_label=verified_label,
            comments=comments,
        )
    )
    await db.flush()
    image = (await db.execute(select(LeafImage).where(LeafImage.image_id == d.image_id))).scalar_one()
    return _diagnosis_to_out(d, image)
