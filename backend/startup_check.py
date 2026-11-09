"""Preflight checks for the CassavaGuard backend (run by start-backend.bat).

Verifies that everything the API needs is in place BEFORE uvicorn starts and
prints an exact fix command for anything that is missing.

Checks: Python deps, backend\\.env, database reachability, ML model file,
port 8000 availability, CORS origins.

Exit codes:
    0 → safe to start
    1 → fix the reported problem first
    2 → a healthy CassavaGuard API is already running (don't start a second one)
"""

from __future__ import annotations

import socket
import sys
import urllib.parse
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent

OK, WARN, FAIL = "OK", "WARN", "FAIL"
_symbols = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}
_failures = 0
_already_running = False


def report(level: str, message: str, fix: str | None = None) -> None:
    global _failures
    print(f"{_symbols[level]} {message}")
    if fix:
        for line in fix.splitlines():
            print(f"       {line}")
    if level == FAIL:
        _failures += 1


def check_python_deps() -> None:
    import importlib.util

    # find_spec checks presence without paying the import cost (onnxruntime etc.)
    required = [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("sqlalchemy", "sqlalchemy[asyncio]"),
        ("pydantic_settings", "pydantic-settings"),
        ("asyncpg", "asyncpg"),
        ("aiosqlite", "aiosqlite"),
        ("PIL", "pillow"),
        ("numpy", "numpy"),
        ("onnxruntime", "onnxruntime"),
        ("jwt", "PyJWT"),
        ("bcrypt", "bcrypt"),
    ]
    missing = [pkg for mod, pkg in required if importlib.util.find_spec(mod) is None]
    if missing:
        report(
            FAIL,
            f"Python packages missing: {', '.join(missing)}",
            "cd /d " + str(PROJECT_DIR) + "\n"
            "venv\\Scripts\\python.exe -m pip install -r backend\\requirements.txt",
        )
    else:
        report(OK, f"Python packages installed (Python {sys.version.split()[0]})")


def check_env_file() -> dict[str, str]:
    env_path = BACKEND_DIR / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        example = BACKEND_DIR / ".env.example"
        fix = None
        if example.exists():
            fix = f'copy "{example}" "{env_path}"'
        report(WARN, ".env not found — using built-in defaults", fix)
        return values
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()
    report(OK, f"Config loaded ({env_path.name})")
    return values


def check_database(env: dict[str, str]) -> None:
    url = env.get(
        "DATABASE_URL", "postgresql+asyncpg://cassava:cassava@localhost:5432/cassava"
    )
    if url.startswith("sqlite"):
        db_path = url.split("///", 1)[-1]
        full = (BACKEND_DIR / db_path).resolve() if not Path(db_path).is_absolute() else Path(db_path)
        report(OK, f"Database: SQLite ({full})", None)
        return

    parsed = urllib.parse.urlsplit(url.replace("+asyncpg", "").replace("+psycopg", ""))
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
        report(OK, f"Database: PostgreSQL reachable at {host}:{port}")
    except OSError as exc:
        report(
            FAIL,
            f"Database: cannot reach PostgreSQL at {host}:{port} ({exc.strerror or exc})",
            "Start the database, e.g.:\n"
            "    docker compose up -d db\n"
            "or point backend\\.env at another database (see docs\\DATABASE.md):\n"
            "    DATABASE_URL=sqlite+aiosqlite:///./cassava_guard.db",
        )


def check_model(env: dict[str, str]) -> None:
    default = PROJECT_DIR / "ml" / "models" / "mobilenetv2_cassava.onnx"
    model = Path(env.get("MODEL_PATH", str(default)))
    if not model.is_absolute():
        model = (PROJECT_DIR / model).resolve()  # relative = from project root
    if model.exists():
        report(OK, f"Model file: {model} ({model.stat().st_size // 1024} KB)")
    else:
        report(
            WARN,
            f"Model file not found: {model} — the API falls back to the mock classifier",
            "Either export the model (see README → ML Model) or fix MODEL_PATH in backend\\.env",
        )


def check_port(port: int = 8000) -> None:
    # Something already listening? Maybe our own backend is running.
    global _already_running
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except Exception:
        payload = None

    if isinstance(payload, dict) and "status" in payload:
        # It answers our /health contract — a healthy CassavaGuard instance.
        _already_running = True
        report(
            OK,
            f"The CassavaGuard API is already running at http://127.0.0.1:{port}",
            "Open http://localhost:5173 — nothing else to start. To restart it:\n"
            f"    netstat -ano | findstr :{port}\n"
            f"    taskkill /F /PID <PID>",
        )
        return
    if payload is not None:
        # Some other service owns the port — that IS a problem.
        report(
            FAIL,
            f"Port {port} is used by another service (not CassavaGuard)",
            f"    netstat -ano | findstr :{port}\n"
            f"    taskkill /F /PID <PID>",
        )
        return

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
        report(OK, f"Port {port} is free")
    except OSError:
        report(
            FAIL,
            f"Port {port} is in use by another process",
            f"    netstat -ano | findstr :{port}\n"
            f"    taskkill /F /PID <PID>",
        )


def check_cors(env: dict[str, str]) -> None:
    origins = env.get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )
    report(OK, f"CORS origins: {origins}")


def main() -> int:
    print("CassavaGuard backend — preflight checks")
    print("-" * 44)
    check_python_deps()
    env = check_env_file()
    check_database(env)
    check_model(env)
    check_port()
    check_cors(env)
    print("-" * 44)
    if _failures:
        print(f"{_failures} problem(s) found — fix them before starting.")
        return 1
    if _already_running:
        print("A healthy CassavaGuard API is already running — not starting a second one.")
        print("Use it: http://localhost:5173")
        return 2
    print("All checks passed. Starting the API on http://127.0.0.1:8000")
    print("Health probe: http://127.0.0.1:8000/health")
    return 0


if __name__ == "__main__":
    sys.exit(main())
