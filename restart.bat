@echo off
REM EyeProtect - restart / apply config (double-click to run)
setlocal
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

%PY% "%~dp0restart_service.py"

echo.
pause
