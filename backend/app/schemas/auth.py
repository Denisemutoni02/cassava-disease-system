"""Auth-related request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator

# EmailStr requires the email-validator package; keep a light fallback.
try:
    import email_validator  # noqa: F401
    _EMAIL_OK = True
except ImportError:
    _EMAIL_OK = False


class RegisterRequest(BaseModel):
    """Self-registration payload. Role is limited to farmer|officer
    (admins are created by the seed script or another admin)."""

    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=6, max_length=128)
    phone: str | None = Field(default=None, max_length=20, pattern=r"^\+?[0-9\s\-]{7,20}$")
    email: str | None = Field(default=None, max_length=160)
    role: str = Field(default="farmer", pattern="^(farmer|officer)$")

    @model_validator(mode="after")
    def _contact_required(self):
        if not self.phone and not self.email:
            raise ValueError("Provide a phone number or an email address")
        return self


class LoginRequest(BaseModel):
    """Login with phone number *or* email in a single identifier field."""

    identifier: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
