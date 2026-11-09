@echo off
REM CassavaGuard - Backend Startup (Windows)
REM Delegates to backend\start-backend.bat (runs the preflight checks, then uvicorn).
call "%~dp0backend\start-backend.bat"
