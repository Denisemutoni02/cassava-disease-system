"""Build the Vite frontend before Vercel packages the FastAPI application."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
npm = "npm.cmd" if sys.platform == "win32" else "npm"

subprocess.run([npm, "ci"], cwd=FRONTEND, check=True)
subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)
