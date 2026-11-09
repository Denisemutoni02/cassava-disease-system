"""Admin endpoints: user management, system stats, model registry."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.deps import AdminUser, DbSession
from app.models import Diagnosis, HotspotCluster, LeafImage, ModelVersion, User
from app.schemas.admin import AdminStats, ModelVersionOut, UserAdminOut
from app.services.classifier import get_classifier

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserAdminOut], summary="List all users")
async def list_users(
    db: DbSession,
    admin: AdminUser,
    role: Annotated[str | None, Query(pattern="^(farmer|officer|admin)$")] = None,
) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc())
    if role:
        stmt = stmt.where(User.role == role)
    return list((await db.execute(stmt)).scalars().all())


@router.patch(
    "/users/{user_id}/toggle-active",
    response_model=UserAdminOut,
    summary="Activate or deactivate a user",
)
async def toggle_active(user_id: str, db: DbSession, admin: AdminUser) -> User:
    user = (await db.execute(select(User).where(User.user_id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    user.is_active = not user.is_active
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/model", response_model=ModelVersionOut | None, summary="Active model version")
async def active_model(db: DbSession, admin: AdminUser) -> ModelVersion | None:
    return (
        await db.execute(
            select(ModelVersion)
            .where(ModelVersion.is_active.is_(True))
            .order_by(ModelVersion.deployed_at.desc())
        )
    ).scalars().first()


@router.get("/stats", response_model=AdminStats, summary="System-wide statistics")
async def stats(db: DbSession, admin: AdminUser) -> AdminStats:
    def _count(label: str | None = None) -> int:
        return label

    users_total = (await db.execute(select(func.count(User.user_id)))).scalar_one()
    farmers = (
        await db.execute(select(func.count(User.user_id)).where(User.role == "farmer"))
    ).scalar_one()
    officers = (
        await db.execute(select(func.count(User.user_id)).where(User.role == "officer"))
    ).scalar_one()

    label_rows = (
        await db.execute(select(Diagnosis.disease_label, func.count()).group_by(Diagnosis.disease_label))
    ).all()
    by_label = {r[0]: r[1] for r in label_rows}
    diagnoses_total = sum(by_label.values())
    active_clusters = (
        await db.execute(select(func.count(HotspotCluster.cluster_id)))
    ).scalar_one()
    active_model = (
        await db.execute(
            select(ModelVersion)
            .where(ModelVersion.is_active.is_(True))
            .order_by(ModelVersion.deployed_at.desc())
        )
    ).scalars().first()

    return AdminStats(
        users=users_total,
        farmers=farmers,
        officers=officers,
        diagnoses_total=diagnoses_total,
        diagnoses_cmd=by_label.get("CMD", 0),
        diagnoses_cbsd=by_label.get("CBSD", 0),
        diagnoses_healthy=by_label.get("Healthy", 0),
        diagnoses_uncertain=by_label.get("Uncertain", 0),
        active_clusters=active_clusters,
        active_model=ModelVersionOut.model_validate(active_model) if active_model else None,
        classifier_mode=get_classifier().mode,
    )
