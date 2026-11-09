#!/usr/bin/env bash
# ============================================================
#  CassavaGuard - ONE-CLICK START (backend + frontend + data)
#
#  Linux / macOS / WSL:
#      ./start_system.sh
#
#  First run it will:
#    1. create the Python virtual environment (.venv) and install deps
#    2. create backend/.env from backend/.env.example
#    3. seed the database with demo accounts/data
#    4. start backend on :8000 and frontend on :5173 (logs in ./logs)
#
#  Stop with ./stop_system.sh (Ctrl+C also stops both).
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
VENV="$ROOT/.venv"
PYBIN="$VENV/bin/python"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"

say()  { printf '  %s\n' "$*"; }
head1() { printf '\n============================================================\n  %s\n============================================================\n' "$*"; }

# ---- 0. toolchain checks --------------------------------------------------
command -v python3 >/dev/null 2>&1 || { echo "[FAIL] python3 not found - install Python 3.10-3.13"; exit 1; }
command -v node    >/dev/null 2>&1 || { echo "[FAIL] node not found - install Node.js 18+"; exit 1; }

head1 "CassavaGuard - starting system"

# ---- 1. Python virtual environment ---------------------------------------
if [ -x "$PYBIN" ]; then
    say "[1/4] Virtual environment found."
else
    say "[1/4] First run - creating virtual environment..."
    python3 -m venv "$VENV"
    "$PYBIN" -m pip install --upgrade pip >/dev/null
    "$PYBIN" -m pip install -r "$ROOT/backend/requirements.txt"
fi

# ---- 2. Config ------------------------------------------------------------
if [ -f "$ROOT/backend/.env" ]; then
    say "[2/4] backend/.env found."
else
    say "[2/4] Creating backend/.env from backend/.env.example"
    cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
fi

# ---- 3. Database (seed on first run only) --------------------------------
if [ -f "$ROOT/backend/cassava_guard.db" ]; then
    say "[3/4] Database found - keeping existing data."
else
    say "[3/4] First run - seeding demo accounts, diagnoses and hotspots..."
    ( cd "$ROOT/backend" && "$PYBIN" scripts/seed.py )
fi

# ---- 4. Launch both services ---------------------------------------------
say "[4/4] Launching backend (:8000) and frontend (:5173)..."

# Kill anything we started previously (pidfiles), ignoring "not running".
[ -f "$LOGS/backend.pid" ]  && kill "$(cat "$LOGS/backend.pid")"  2>/dev/null || true
[ -f "$LOGS/frontend.pid" ] && kill "$(cat "$LOGS/frontend.pid")" 2>/dev/null || true

launch() { # $1 = name, $2 = workdir, rest = command...
    local name="$1" dir="$2"; shift 2
    ( cd "$dir" && exec "$@" ) >"$LOGS/$name.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$LOGS/$name.pid"
    say "  $name started (pid $pid) - log: logs/$name.log"
}

launch backend  "$ROOT/backend"  "$PYBIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
if [ ! -d "$ROOT/frontend/node_modules" ]; then
    say "  installing frontend dependencies (npm install)..."
    ( cd "$ROOT/frontend" && npm install ) >/dev/null
fi
launch frontend "$ROOT/frontend" npm run dev

cleanup() {
    echo
    echo "Stopping CassavaGuard..."
    for name in backend frontend; do
        if [ -f "$LOGS/$name.pid" ]; then
            pid="$(cat "$LOGS/$name.pid")"
            kill "$pid" 2>/dev/null || true
            # uvicorn --reload runs a child worker; take the group down too
            pkill -TERM -P "$pid" 2>/dev/null || true
            rm -f "$LOGS/$name.pid"
        fi
    done
    echo "Stopped."
}
trap cleanup INT TERM EXIT

# ---- 5. Wait for readiness, then report ----------------------------------
ready=""
for i in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done

echo
if [ -n "$ready" ]; then
    echo "  App     : http://localhost:5173"
    echo "  API     : http://127.0.0.1:8000/health  (classifier: onnx)"
    echo "  Swagger : http://127.0.0.1:8000/docs"
    echo "  Login   : farmer1@example.com / Farmer@123"
else
    echo "  [WARN] Backend not answering yet - check logs/backend.log"
fi
echo
echo "  Press Ctrl+C to stop both services."
echo

wait
