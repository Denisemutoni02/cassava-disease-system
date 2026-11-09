@echo off
REM ============================================================
REM  CassavaGuard - STOP (kills the API on :8000 and Vite on :5173)
REM  Safe to run at any time; reports if nothing was listening.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title CassavaGuard stop

set FOUND=0

echo Stopping CassavaGuard...
echo.

REM --- backend (uvicorn on 8000) ---
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r ":8000 .*LISTENING"') do (
    echo   killing API process PID %%P
    taskkill /F /PID %%P >nul 2>nul
    if not errorlevel 1 set FOUND=1
)

REM --- frontend (vite on 5173) ---
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r ":5173 .*LISTENING"') do (
    echo   killing frontend process PID %%P
    taskkill /F /PID %%P >nul 2>nul
    if not errorlevel 1 set FOUND=1
)

echo.
if "!FOUND!"=="1" (
    echo Done. CassavaGuard is stopped.
) else (
    echo Nothing was listening on ports 8000/5173 - system was already stopped.
)
echo.
echo %cmdcmdline% | findstr /i /c:"/c" >nul && pause
endlocal
exit /b 0
