"""Authentication endpoints: register, login, current user."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select

from app.deps import CurrentUser, DbSession
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new farmer or extension officer",
)
async def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    """Create an account and return a JWT immediately (auto-login).

    Public registration is limited to ``farmer`` and ``officer`` roles.
    Admin accounts are provisioned via the seed script.
    """
    # Uniqueness check on phone / email
    conditions = []
    if payload.phone:
        conditions.append(User.phone == payload.phone)
    if payload.email:
        conditions.append(User.email == payload.email.lower())
    if conditions:
        existing = (await db.execute(select(User).where(or_(*conditions)))).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this phone number or email already exists.",
            )

    user = User(
        full_name=payload.full_name.strip(),
        phone=payload.phone,
        email=payload.email.lower() if payload.email else None,
        role=payload.role,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    token = create_access_token(user.user_id, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse, summary="Log in with phone/email + password")
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    """Authenticate with either a phone number or email as the identifier."""
    identifier = payload.identifier.strip()
    candidate = identifier.lower() if "@" in identifier else identifier

    user = (
        await db.execute(
            select(User).where(or_(User.phone == identifier, User.email == candidate))
        )
    ).scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect identifier or password.",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated.")

    token = create_access_token(user.user_id, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="Get the logged-in user's profile")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
