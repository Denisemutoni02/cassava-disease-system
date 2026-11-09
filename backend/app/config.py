"""Application configuration loaded from environment variables (.env)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory (one level above the app package: backend/app/config.py)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
# monorepo root (backend, frontend, ml, data)
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Runtime settings. Override any value with an environment variable."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core ---
    app_name: str = "CassavaGuard API"
    environment: str = "development"          # development | test | production
    debug: bool = True

    # --- Database (PostgreSQL + PostGIS in production; SQLite allowed for tests) ---
    database_url: str = "postgresql+asyncpg://cassava:cassava@localhost:5432/cassava"

    # --- Auth ---
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # --- ML model ---
    # Default: the ONNX export produced by ml/quantise.py (loads with
    # onnxruntime, which works on Python 3.12). Override with MODEL_PATH,
    # e.g. ...\mobilenetv2_cassava_dynamic.tflite when tflite-runtime is installed.
    model_path: str = str(PROJECT_ROOT / "ml" / "models" / "mobilenetv2_cassava.onnx")
    confidence_threshold: float = 0.60          # below → label "Uncertain"
    force_mock_model: bool = False              # True → always use the deterministic mock

    # --- Uploads ---
    upload_dir: str = str(BACKEND_ROOT / "uploads")
    max_upload_mb: int = 8
    allowed_image_types: str = "image/jpeg,image/png,image/webp"

    # --- Clustering ---
    cluster_eps_m: float = 2000.0               # DBSCAN neighbourhood radius (metres)
    cluster_min_samples: int = 3                # minimum diagnoses to form a hotspot
    cluster_window_days: int = 90               # only consider recent diagnoses

    # --- CORS (frontend dev server) ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Single-host deployment: also serve the built SPA (frontend/dist) ---
    # Off in dev (Vite serves the UI); true in deployment images so one
    # process answers both the API and the web app.
    serve_frontend: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_image_type_list(self) -> list[str]:
        return [t.strip().lower() for t in self.allowed_image_types.split(",") if t.strip()]

    @property
    def upload_path(self) -> Path:
        # Relative paths resolve from backend/ (so UPLOAD_DIR=./uploads is stable
        # no matter which directory uvicorn was started from).
        p = Path(self.upload_dir)
        return p if p.is_absolute() else (BACKEND_ROOT / p).resolve()

    @property
    def model_file(self) -> Path:
        # Relative paths resolve from the project root, so a packaged copy works
        # on any machine: MODEL_PATH=ml/models/mobilenetv2_cassava.onnx
        p = Path(self.model_path)
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
