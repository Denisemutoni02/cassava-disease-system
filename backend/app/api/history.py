"""Diagnosis history endpoint: the logged-in user's past diagnoses.

``GET /api/v1/history`` is a thin alias of the ``/diagnoses`` list restricted
to ``scope=mine`` — the data source for the frontend history page.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.diagnoses import list_diagnoses
from app.deps import CurrentUser, DbSession
from app.schemas.diagnosis import DiagnosisPage

router = APIRouter(prefix="/history", tags=["history"])


@router.get(
    "",
    response_model=DiagnosisPage,
    summary="My past diagnoses (JWT)",
)
async def my_history(
    db: DbSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    label: Annotated[str | None, Query(pattern="^(CMD|CBSD|Healthy|Uncertain)$")] = None,
) -> DiagnosisPage:
    """Paginated history of this user's diagnoses, newest first."""
    return await list_diagnoses(
        db=db, user=user, page=page, page_size=page_size, scope="mine", label=label
    )
