"""FastAPI application factory and entry point.

Run with:
    uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, auth, clusters, diagnose, diagnoses, farms, history, hotspots
from app.config import PROJECT_ROOT, get_settings
from app.db import init_db
from app.services.classifier import get_classifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("cassavaguard")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load the ML model once per worker; init DB in dev/test."""
    settings = get_settings()
    classifier = get_classifier()  # tflite | onnx | mock
    logger.info("CassavaGuard API starting · classifier=%s · env=%s", classifier.mode, settings.environment)

    if settings.environment in ("development", "test"):
        try:
            await init_db()
            logger.info("Database schema ensured (dev/test bootstrap)")
        except Exception:
            logger.exception("Database bootstrap failed – is the DB reachable?")

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "Cassava leaf disease detection (CMD / CBSD / Healthy) with outbreak "
            "hotspot mapping for MuZARDI, Uganda.\n\n"
            "**Online-only system** – image upload, CNN inference, risk advice and "
            "hotspot map updates all require an active internet connection. "
            "Inference runs on this server (never in the browser)."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS: default allows the Vite dev server (localhost/127.0.0.1:5173).
    # Set CORS_ORIGINS=* in backend\.env to allow any origin (LAN/phone testing).
    cors_origins = settings.cors_origin_list
    allow_all = "*" in cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else cors_origins,
        # Credentials only pair with explicit origins; JWT auth uses a header,
        # so wildcard (*) needs credentials off to be accepted by browsers.
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_prefix = "/api/v1"
    app.include_router(diagnose.router)          # POST /diagnose (JWT: infer + save + cluster)
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(farms.router, prefix=api_prefix)
    app.include_router(diagnoses.router, prefix=api_prefix)
    app.include_router(history.router, prefix=api_prefix)   # GET /api/v1/history (JWT)
    app.include_router(hotspots.router, prefix=api_prefix)  # GET /api/v1/hotspots (JWT)
    app.include_router(clusters.router, prefix=api_prefix)
    app.include_router(admin.router, prefix=api_prefix)

    @app.get("/health", tags=["system"], summary="Liveness probe")
    async def health() -> dict:
        clf = get_classifier()
        return {
            "status": "ok",
            "classifier": clf.mode,
            "model_version": clf.version_tag,
            "online_required": True,
        }

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error. Please try again."},
        )

    # --- Optional: serve the built SPA from the same process ---------------
    # SERVE_FRONTEND=true + frontend/dist present => one host serves both the
    # API and the web app (deployment images / single-service hosting).
    # Registered last, so every API route above keeps priority.
    if settings.serve_frontend:
        dist = (PROJECT_ROOT / "frontend" / "dist").resolve()
        if dist.is_dir():
            from fastapi.responses import FileResponse

            @app.get("/{full_path:path}", include_in_schema=False)
            async def spa(full_path: str) -> FileResponse | JSONResponse:
                if full_path.startswith(("api/", "docs", "redoc", "openapi")):
                    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND,
                                        content={"detail": "Not Found"})
                target = (dist / full_path).resolve()
                if full_path and target.is_relative_to(dist) and target.is_file():
                    return FileResponse(target)          # hashed JS/CSS/assets
                return FileResponse(dist / "index.html")  # SPA route (deep links)

            logger.info("Serving built frontend from %s", dist)
        else:
            logger.warning(
                "SERVE_FRONTEND=true but %s is missing — run `npm run build` in frontend/",
                dist,
            )

    return app


app = create_app()
