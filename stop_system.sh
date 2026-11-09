#!/usr/bin/env bash
# ============================================================
#  CassavaGuard - STOP (kills backend :8000 and frontend :5173)
#  Usage: ./stop_system.sh
# ============================================================
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGS="$ROOT/logs"
stopped=0

echo "Stopping CassavaGuard..."

# 1. Anything we recorded in pidfiles
for name in backend frontend; do
    pidfile="$LOGS/$name.pid"
    if [ -f "$pidfile" ]; then
        pid="$(cat "$pidfile")"
        if kill "$pid" 2>/dev/null; then
            echo "  $name (pid $pid) stopped"
            stopped=1
        fi
        pkill -TERM -P "$pid" 2>/dev/null || true
        rm -f "$pidfile"
    fi
done

# 2. Fallback: whatever still owns the ports
for port in 8000 5173; do
    if command -v fuser >/dev/null 2>&1; then
        if fuser -k "$port/tcp" >/dev/null 2>&1; then echo "  freed port $port"; stopped=1; fi
    elif command -v lsof >/dev/null 2>&1; then
        pids="$(lsof -ti ":$port" 2>/dev/null || true)"
        [ -n "$pids" ] && { kill $pids 2>/dev/null; echo "  freed port $port"; stopped=1; }
    fi
done

if [ "$stopped" -eq 0 ]; then
    echo "  Nothing was running - system already stopped."
else
    echo "Done."
fi
