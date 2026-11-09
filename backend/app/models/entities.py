"""ORM entity definitions for the cassava disease system.

Geography columns use GeoAlchemy2 on PostgreSQL. For unit tests on SQLite the
same columns fall back to plain TEXT (WKT strings) via ``.with_variant``.
Application logic always reads/writes the ``latitude`` / ``longitude`` float
columns so it stays dialect-agnostic; the PostGIS point is kept in sync for
spatial indexes and future geographic SQL queries.
"""

import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

from app.db import Base

# ---------------------------------------------------------------------------
# Portable UUID + enum helpers (work on PostgreSQL and SQLite)
# ---------------------------------------------------------------------------


class GUID(TypeDecorator):
    """Platform-independent UUID type stored as CHAR(36) on SQLite."""

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        return value


def _enum(name: str, values: list[str]) -> Enum:
    """Native ENUM on PostgreSQL, VARCHAR check-free on SQLite."""
    return Enum(*values, name=name, native_enum=True)


UserROle_VALUES = ["farmer", "officer", "admin"]
DISEASE_VALUES = ["CMD", "CBSD", "Healthy", "Uncertain"]
SEVERITY_VALUES = ["Low", "Moderate", "High"]
RISK_VALUES = ["Low", "Emerging", "High"]


def GeographyPoint():
    """GEOGRAPHY(Point, 4326) with a SQLite TEXT fallback."""
    return Geography("POINT", srid=4326, spatial_index=False).with_variant(Text, "sqlite")


def JSONType():
    return JSON().with_variant(JSONB(), "postgresql")


# ---------------------------------------------------------------------------
# Users & farms
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(160), unique=True)
    role: Mapped[str] = mapped_column(
        _enum("user_role", UserROle_VALUES), nullable=False, default="farmer"
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    farms: Mapped[list["Farm"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Farm(Base):
    __tablename__ = "farms"

    farm_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    farm_name: Mapped[str] = mapped_column(String(120), nullable=False)
    district: Mapped[str | None] = mapped_column(String(80))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    location = mapped_column(GeographyPoint(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    owner: Mapped[User] = relationship(back_populates="farms")


# ---------------------------------------------------------------------------
# Model registry, images, diagnoses, advice
# ---------------------------------------------------------------------------


class ModelVersion(Base):
    __tablename__ = "model_versions"

    model_version_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    version_tag: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    architecture: Mapped[str] = mapped_column(String(50), nullable=False, default="MobileNetV2")
    file_path: Mapped[str | None] = mapped_column(String(255))
    val_accuracy: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class LeafImage(Base):
    __tablename__ = "leaf_images"

    image_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    farm_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("farms.farm_id", ondelete="SET NULL")
    )
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    gps_location = mapped_column(GeographyPoint(), nullable=True)
    gps_accuracy_m: Mapped[float | None] = mapped_column(Float)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    # Relationships give SQLAlchemy the flush-time dependency edges it needs to
    # INSERT parent rows (users/farms) before this table — FKs alone are not
    # enough (SQLite never enforced this, PostgreSQL does).
    user: Mapped["User"] = relationship()
    farm: Mapped["Farm | None"] = relationship()


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    diagnosis_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("leaf_images.image_id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("model_versions.model_version_id", ondelete="SET NULL")
    )
    disease_label: Mapped[str] = mapped_column(
        _enum("disease_label", DISEASE_VALUES), nullable=False
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    inferred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    image: Mapped["LeafImage"] = relationship()
    model_version: Mapped["ModelVersion | None"] = relationship()
    advice: Mapped["Advice | None"] = relationship(
        back_populates="diagnosis", cascade="all, delete-orphan", uselist=False
    )


class Advice(Base):
    __tablename__ = "advice"

    advice_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    diagnosis_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("diagnoses.diagnosis_id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    advice_text: Mapped[str] = mapped_column(Text, nullable=False)
    severity_level: Mapped[str] = mapped_column(
        _enum("severity_level", SEVERITY_VALUES), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    diagnosis: Mapped[Diagnosis] = relationship(back_populates="advice")


# ---------------------------------------------------------------------------
# Risk rules
# ---------------------------------------------------------------------------


class RiskRule(Base):
    __tablename__ = "risk_rules"

    rule_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    disease_label: Mapped[str] = mapped_column(_enum("disease_label", DISEASE_VALUES), nullable=False)
    min_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.60)
    severity_level: Mapped[str] = mapped_column(
        _enum("severity_level", SEVERITY_VALUES), nullable=False
    )
    advice_template: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.user_id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    updated_by_user: Mapped["User | None"] = relationship()


# ---------------------------------------------------------------------------
# Hotspot clusters (derived data)
# ---------------------------------------------------------------------------


class HotspotCluster(Base):
    __tablename__ = "hotspot_clusters"

    cluster_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    centroid = mapped_column(GeographyPoint(), nullable=True)  # NULL on SQLite; set via lat/lon
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_m: Mapped[float] = mapped_column(Float, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dominant_disease: Mapped[str] = mapped_column(
        _enum("disease_label", DISEASE_VALUES), nullable=False
    )
    risk_level: Mapped[str] = mapped_column(_enum("risk_level", RISK_VALUES), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(20), nullable=False, default="DBSCAN")
    eps_m: Mapped[float] = mapped_column(Float, nullable=False)
    min_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    members: Mapped[list["ClusterMember"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )


class ClusterMember(Base):
    __tablename__ = "cluster_members"
    __table_args__ = (UniqueConstraint("cluster_id", "diagnosis_id"),)

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("hotspot_clusters.cluster_id", ondelete="CASCADE"), primary_key=True
    )
    diagnosis_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("diagnoses.diagnosis_id", ondelete="CASCADE"), primary_key=True
    )

    cluster: Mapped[HotspotCluster] = relationship(back_populates="members")
    diagnosis: Mapped["Diagnosis"] = relationship()


class DiagnosisFeedback(Base):
    __tablename__ = "diagnosis_feedback"

    feedback_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    diagnosis_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("diagnoses.diagnosis_id", ondelete="CASCADE"), nullable=False
    )
    officer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    verified_label: Mapped[str] = mapped_column(
        _enum("disease_label", DISEASE_VALUES), nullable=False
    )
    comments: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    diagnosis: Mapped[Diagnosis] = relationship()
    officer: Mapped["User"] = relationship()
