@echo off
REM CassavaGuard - Frontend Startup (Windows)
REM Delegates to frontend\start-frontend.bat (checks node_modules, runs Vite, opens the browser).
call "%~dp0frontend\start-frontend.bat"
