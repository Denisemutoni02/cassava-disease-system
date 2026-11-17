"""Vercel entry point for the combined CassavaGuard frontend and API."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

if os.getenv("VERCEL"):
    # Vercel's filesystem is read-only except for /tmp. Keep uploads available
    # during inference without relying on a non-persistent deployment folder.
    os.environ.setdefault("ENVIRONMENT", "production")
    os.environ.setdefault("SERVE_FRONTEND", "true")
    os.environ.setdefault("UPLOAD_DIR", "/tmp/cassavaguard-uploads")

from app.main import app  # noqa: E402

