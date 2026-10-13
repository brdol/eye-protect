@echo off
REM EyeProtect - remove auto-start (double-click to run)
setlocal
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

%PY% "%~dp0uninstall_service.py"

echo.
pause
