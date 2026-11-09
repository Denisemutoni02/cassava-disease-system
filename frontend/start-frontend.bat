@echo off
REM ============================================================
REM  CassavaGuard - Frontend startup (Windows)
REM  Double-click this file, or run it from a terminal:
REM      cd /d E:\cassava-disease-system\frontend
REM      start-frontend.bat
REM  Opens the app at http://localhost:5173
REM ============================================================
setlocal
cd /d "%~dp0"
title CassavaGuard frontend (port 5173)

where npm >nul 2>nul
if errorlevel 1 goto :no_npm

if not exist "node_modules" goto :no_modules

if not exist ".env" (
    echo [WARN] frontend\.env not found - the API URL falls back to http://localhost:8000
    echo        To override it: set VITE_API_URL=http://localhost:8000 in frontend\.env
)

echo.
echo === CassavaGuard frontend ===
echo Starting the dev server; the browser will open http://localhost:5173 in a few seconds.
echo The backend must be running (backend\start-backend.bat) for login and diagnosis.
echo.
start "" /b cmd /c "ping -n 6 127.0.0.1 >nul & start http://localhost:5173/"
npm run dev
goto :end

:no_npm
echo.
echo [FAIL] npm was not found on PATH - Node.js does not seem to be installed.
echo.
echo Fix:
echo        1. Install Node.js 18+ from https://nodejs.org
echo        2. Close this window, open a NEW terminal, then run this script again
echo.
goto :fail

:no_modules
echo.
echo [FAIL] node_modules not found in %~dp0
echo.
echo Fix - run this command once:
echo        cd /d %~dp0
echo        npm install
echo.
goto :fail

:fail
echo %cmdcmdline% | findstr /i /c:"/c" >nul && pause
exit /b 1

:end
echo.
echo Frontend stopped.
echo %cmdcmdline% | findstr /i /c:"/c" >nul && pause
endlocal
