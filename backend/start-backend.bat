@echo off
REM ============================================================
REM  CassavaGuard - Backend startup (Windows)
REM  Double-click this file, or run it from a terminal:
REM      cd /d E:\cassava-disease-system\backend
REM      start-backend.bat
REM ============================================================
setlocal
cd /d "%~dp0"
title CassavaGuard backend (port 8000)

if not exist "..\venv\Scripts\python.exe" goto :no_venv

echo.
echo === CassavaGuard backend - preflight checks ===
"..\venv\Scripts\python.exe" startup_check.py
set CHK=%errorlevel%
if "%CHK%"=="2" goto :already_running
if not "%CHK%"=="0" goto :checks_failed

echo.
"..\venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
goto :end

:already_running
echo.
echo The API is already running - open http://localhost:5173 to use it.
echo Nothing to start. Close this window, or stop the other instance first
echo if you actually wanted a restart:
echo        netstat -ano ^| findstr :8000
echo        taskkill /F /PID ^<PID^>
echo.
echo %cmdcmdline% | findstr /i /c:"/c" >nul && pause
exit /b 0

:no_venv
echo.
echo [FAIL] Python virtual environment not found at:
echo        %~dp0..\venv
echo.
echo Fix - run these commands once:
echo        cd /d %~dp0..
echo        py -3.12 -m venv venv
echo        venv\Scripts\python.exe -m pip install -r backend\requirements.txt
echo.
goto :fail

:checks_failed
echo.
echo [FAIL] Preflight checks failed - fix the issues above and run this again.
echo.
goto :fail

:fail
REM Keep the window open only when double-clicked (cmd /c), not in a terminal.
echo %cmdcmdline% | findstr /i /c:"/c" >nul && pause
exit /b 1

:end
echo.
echo Backend stopped.
echo %cmdcmdline% | findstr /i /c:"/c" >nul && pause
endlocal
