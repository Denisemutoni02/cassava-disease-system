"""Farm registration endpoints."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentUser, DbSession
from app.models import Farm
from app.schemas.diagnosis import FarmCreate, FarmOut

router = APIRouter(prefix="/farms", tags=["farms"])


def _attach_postgis_point(farm: Farm, db: AsyncSession) -> None:
    """Set the PostGIS geography column when running on PostgreSQL."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        from geoalchemy2.elements import WKTElement

        farm.location = WKTElement(f"POINT({farm.longitude} {farm.latitude})", srid=4326)


@router.post(
    "",
    response_model=FarmOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a farm with a GPS location",
)
async def create_farm(payload: FarmCreate, db: DbSession, user: CurrentUser) -> Farm:
    farm = Farm(
        user_id=user.user_id,
        farm_name=payload.farm_name.strip(),
        district=payload.district,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    _attach_postgis_point(farm, db)
    db.add(farm)
    await db.flush()
    await db.refresh(farm)
    return farm


@router.get("", response_model=list[FarmOut], summary="List my farms")
async def list_my_farms(db: DbSession, user: CurrentUser) -> list[Farm]:
    result = await db.execute(
        select(Farm).where(Farm.user_id == user.user_id).order_by(Farm.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{farm_id}", response_model=FarmOut, summary="Get one of my farms")
async def get_farm(farm_id: str, db: DbSession, user: CurrentUser) -> Farm:
    farm = (
        await db.execute(select(Farm).where(Farm.farm_id == farm_id, Farm.user_id == user.user_id))
    ).scalar_one_or_none()
    if farm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found.")
    return farm
