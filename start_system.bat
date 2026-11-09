@echo off
REM ============================================================
REM  CassavaGuard - ONE-CLICK START (backend + frontend + data)
REM
REM  Double-click this file. It will:
REM    1. create the Python virtual environment if missing (first run)
REM    2. create backend\.env from .env.example if missing
REM    3. seed the database with demo accounts/data if missing
REM    4. open the backend (port 8000) and frontend (port 5173)
REM
REM  Stop everything with stop_system.bat (or close both windows).
REM ============================================================
setlocal
cd /d "%~dp0"
title CassavaGuard

echo ============================================================
echo   CassavaGuard - starting system
echo ============================================================

REM --- 1. Python virtual environment --------------------------------------
if exist "venv\Scripts\python.exe" goto :venv_ok
echo [1/4] First run - creating virtual environment, this takes a few minutes...
where py >nul 2>nul
if not errorlevel 1 (py -3.12 -m venv venv) else (python -m venv venv)
if not exist "venv\Scripts\python.exe" goto :fail_venv
venv\Scripts\python.exe -m pip install --upgrade pip >nul
venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto :fail_pip
goto :venv_done

:venv_ok
echo [1/4] Virtual environment found.
:venv_done

REM --- 2. Config ------------------------------------------------------------
if exist "backend\.env" goto :env_ok
echo [2/4] Creating backend\.env from backend\.env.example
copy /Y "backend\.env.example" "backend\.env" >nul
goto :env_done
:env_ok
echo [2/4] backend\.env found.
:env_done

REM --- 3. Database - seed on first run only --------------------------------
if exist "backend\cassava_guard.db" goto :db_ok
echo [3/4] First run - seeding demo accounts, diagnoses and hotspots...
pushd backend
..\venv\Scripts\python.exe scripts\seed.py
if errorlevel 1 (popd & goto :fail_seed)
popd
goto :db_done
:db_ok
echo [3/4] Database found - keeping existing data.
:db_done

REM --- 4. Launch both services in their own windows ------------------------
echo [4/4] Launching backend on port 8000 and frontend on port 5173...
start "CassavaGuard backend"  cmd /k ""%~dp0start_backend.bat""
start "CassavaGuard frontend" cmd /k ""%~dp0start_frontend.bat""

echo.
echo   App     : http://localhost:5173
echo   API     : http://127.0.0.1:8000/health
echo   Swagger : http://localhost:8000/docs
echo   Login   : farmer1@example.com / Farmer@123
echo.
echo   Shut down: run stop_system.bat or close both black windows.
echo.
REM Pause on double-click only; "/auto" skips it for scripted/CI runs.
if /i "%~1"=="/auto" goto :no_pause
echo %cmdcmdline% | findstr /i /c:"/c" >nul && pause
:no_pause
endlocal
exit /b 0

:fail_venv
echo [FAIL] Could not create the virtual environment.
echo        Install Python 3.10-3.13 and run start_system.bat again.
goto :fail

:fail_pip
echo [FAIL] pip install failed - check the output above.
goto :fail

:fail_seed
echo [FAIL] Seeding failed - see the output above.
goto :fail

:fail
echo.
echo   Start aborted - fix the issue above and run start_system.bat again.
echo %cmdcmdline% | findstr /i /c:"/c" >nul && pause
endlocal
exit /b 1
