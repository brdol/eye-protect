@echo off
REM EyeProtect - install auto-start (double-click to run)
setlocal
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

%PY% "%~dp0install_service.py"

echo.
pause
