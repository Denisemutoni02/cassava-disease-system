"""Seed the database with demo data so the system can be showcased
without real MuZARDI photos.

Creates:
  • users (admin / officer / farmers) — passwords documented in README
  • risk rules used by the Risk Engine
  • model version registry entry
  • farms + leaf images + diagnoses + advice clustered around Mukono / Lugazi
  • DBSCAN hotspot clusters computed from the seeded diagnoses

Run AFTER schema.sql has been applied (or init_db.py in dev):
    python scripts/seed.py
"""

import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import (  # noqa: E402
    Advice,
    Diagnosis,
    Farm,
    LeafImage,
    ModelVersion,
    RiskRule,
    User,
)
from app.services.classifier import CLASS_NAMES  # noqa: E402
from app.services.clustering import recompute_clusters  # noqa: E402
from app.services.risk_engine import DEFAULT_RULES  # noqa: E402
from app.services.security import hash_password  # noqa: E402

# Uganda cassava-growing areas (approximate town centres)
MUKONO = (0.3533, 32.7553)
KAYUNGA = (0.7025, 32.8886)
LUGAZI = (0.3167, 32.9167)
MUKONO_UNIV = (0.3386, 32.6233)  # near MuZARDI/UNIK research farms

random.seed(42)  # deterministic seed data


def jitter(centre: tuple[float, float], spread_deg: float = 0.01) -> tuple[float, float]:
    """Random point within ~spread_deg (~1 km) of a centre."""
    return (
        centre[0] + random.uniform(-spread_deg, spread_deg),
        centre[1] + random.uniform(-spread_deg, spread_deg),
    )


async def seed() -> None:
    settings = get_settings()
    await init_db()

    async with SessionLocal() as db:
        # --- Wipe previous demo rows (keep schema) ---
        for table in (Advice, Diagnosis, LeafImage, Farm, RiskRule, ModelVersion):
            await db.execute(delete(table))
        # Keep admin/officer users if they already exist; delete demo farmers
        await db.execute(delete(User).where(User.email.like("farmer%.example.com")))

        # --- Users ---
        admin = User(
            full_name="MuZARDI System Admin",
            email="admin@muzardi.ug",
            phone="+256700000001",
            role="admin",
            password_hash=hash_password("Admin@123"),
        )
        officer = User(
            full_name="Jane Naluggya (Extension Officer)",
            email="officer@muzardi.ug",
            phone="+256700000002",
            role="officer",
            password_hash=hash_password("Officer@123"),
        )
        farmer1 = User(
            full_name="Peter Okello",
            email="farmer1@example.com",
            phone="+256752111222",
            role="farmer",
            password_hash=hash_password("Farmer@123"),
        )
        farmer2 = User(
            full_name="Grace Namutebi",
            email="farmer2@example.com",
            phone="+256752333444",
            role="farmer",
            password_hash=hash_password("Farmer@123"),
        )
        farmer3 = User(
            full_name="Moses Kiggundu",
            email="farmer3@example.com",
            phone="+256752555666",
            role="farmer",
            password_hash=hash_password("Farmer@123"),
        )
        db.add_all([admin, officer, farmer1, farmer2, farmer3])
        await db.flush()

        # --- Risk rules (mirror DEFAULT_RULES) ---
        for label, rule in DEFAULT_RULES.items():
            if label == "Uncertain":
                continue
            db.add(
                RiskRule(
                    disease_label=label,
                    min_confidence=rule["min_confidence"],
                    severity_level=rule["severity_level"],
                    advice_template=rule["advice_template"],
                    updated_by=admin.user_id,
                    is_active=True,
                )
            )

        # --- Model registry ---
        model_path = settings.model_file  # resolved against the project root
        mv = ModelVersion(
            version_tag="mobilenetv2-quantised-demo",
            architecture="MobileNetV2",
            file_path=str(model_path) if model_path.exists() else None,
            # Test accuracy of the deployed ONNX artefact (docs/evaluation_results.md)
            val_accuracy=0.6458 if model_path.exists() else None,
            is_active=True,
        )
        db.add(mv)
        await db.flush()

        # --- Farms ---
        farms = [
            Farm(user_id=farmer1.user_id, farm_name="Mukono Plot A", district="Mukono",
                 latitude=MUKONO[0], longitude=MUKONO[1]),
            Farm(user_id=farmer2.user_id, farm_name="Nakifuma Cassava Field", district="Mukono",
                 latitude=0.3610, longitude=32.8300),
            Farm(user_id=farmer3.user_id, farm_name="Lugazi East Smallholding", district="Buikwe",
                 latitude=LUGAZI[0], longitude=LUGAZI[1]),
            Farm(user_id=farmer1.user_id, farm_name="Kayunga Riverside Plot", district="Kayunga",
                 latitude=KAYUNGA[0], longitude=KAYUNGA[1]),
        ]
        db.add_all(farms)
        await db.flush()

        # --- Diagnoses -------------------------------------------------------
        now = datetime.now(timezone.utc)
        users_cycle = [farmer1, farmer2, farmer3]

        def make_case(
            user: User,
            farm: Farm | None,
            label: str,
            confidence: float,
            lat: float | None,
            lon: float | None,
            days_ago: float,
            severity: str,
            advice_text: str,
        ) -> None:
            # Explicit UUIDs so FK references exist before the shared flush
            image_id, diagnosis_id, advice_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            img = LeafImage(
                image_id=image_id,
                user_id=user.user_id,
                farm_id=farm.farm_id if farm else None,
                file_path=f"seed://{label.lower()}_{uuid.uuid4().hex[:8]}.jpg",
                latitude=lat,
                longitude=lon,
                gps_accuracy_m=8.0 if lat is not None else None,
                uploaded_at=now - timedelta(days=days_ago),
            )
            d = Diagnosis(
                diagnosis_id=diagnosis_id,
                image_id=image_id,
                model_version_id=mv.model_version_id,
                disease_label=label,
                confidence_score=confidence,
                inferred_at=now - timedelta(days=days_ago),
            )
            db.add(Advice(advice_id=advice_id, diagnosis_id=diagnosis_id,
                          advice_text=advice_text, severity_level=severity))
            db.add_all([img, d])

        def disease_advice(label: str, conf: float) -> tuple[str, str]:
            from app.services.risk_engine import RiskEngine

            risk = RiskEngine().evaluate(label, conf, 0.60)
            return risk.advice_text, risk.severity_level

        # CMD hotspot: dense cluster ~ Mukono town (12 cases within ~1.5 km)
        for i in range(12):
            lat, lon = jitter(MUKONO, spread_deg=0.012)
            conf = round(random.uniform(0.78, 0.96), 3)
            text, sev = disease_advice("CMD", conf)
            make_case(random.choice(users_cycle), farms[0], "CMD", conf, lat, lon,
                      random.uniform(1, 40), sev, text)

        # Second smaller CMD cluster near Nakifuma (5 cases)
        for i in range(5):
            lat, lon = jitter((0.3610, 32.8300), spread_deg=0.008)
            conf = round(random.uniform(0.72, 0.91), 3)
            text, sev = disease_advice("CMD", conf)
            make_case(farmer2, farms[1], "CMD", conf, lat, lon,
                      random.uniform(2, 30), sev, text)

        # CBSD hotspot: cluster around Lugazi (7 cases)
        for i in range(7):
            lat, lon = jitter(LUGAZI, spread_deg=0.010)
            conf = round(random.uniform(0.75, 0.94), 3)
            text, sev = disease_advice("CBSD", conf)
            make_case(farmer3, farms[2], "CBSD", conf, lat, lon,
                      random.uniform(1, 25), sev, text)

        # Scattered healthy cases
        for i in range(10):
            centre = random.choice([MUKONO_UNIV, KAYUNGA, MUKONO, LUGAZI])
            lat, lon = jitter(centre, spread_deg=0.02)
            conf = round(random.uniform(0.80, 0.98), 3)
            text, sev = disease_advice("Healthy", conf)
            make_case(random.choice(users_cycle), random.choice(farms), "Healthy", conf, lat, lon,
                      random.uniform(1, 60), sev, text)

        # A few uncertain (low-confidence) cases — excluded from clusters
        for i in range(3):
            lat, lon = jitter(MUKONO, spread_deg=0.015)
            text, sev = disease_advice("CMD", 0.45)  # will become Uncertain
            make_case(farmer1, farms[0], "Uncertain", round(random.uniform(0.35, 0.55), 3),
                      lat, lon, random.uniform(1, 15), "Low", text)

        await db.flush()

        # --- Compute hotspot clusters from the seeded points ---
        clusters = await recompute_clusters(
            db,
            eps_m=settings.cluster_eps_m,
            min_samples=settings.cluster_min_samples,
            window_days=settings.cluster_window_days,
        )

        await db.commit()

    print("Seed complete.")
    print("  Admin login   : admin@muzardi.ug / Admin@123")
    print("  Officer login : officer@muzardi.ug / Officer@123")
    print("  Farmer logins : farmer1..3@example.com / Farmer@123")
    print(f"  Diagnoses seeded; clusters computed: {len(clusters)}")
    for c in clusters:
        print(
            f"    • {c.dominant_disease} ×{c.member_count} "
            f"({c.risk_level}) at ({c.latitude:.4f}, {c.longitude:.4f}) "
            f"r={c.radius_m:.0f} m"
        )


if __name__ == "__main__":
    asyncio.run(seed())
