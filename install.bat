@echo off
REM EyeProtect - install auto-start (double-click to run)
setlocal
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

%PY% "%~dp0install_service.py"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo [FAILED] exit code %RC%
    if "%RC%"=="9009" echo [HINT] Python not found. Install Python or add it to PATH.
) else (
    echo [DONE]
)

REM Pause only when started by Explorer (double-click), not from a terminal.
REM Set EYE_PROTECT_NO_PAUSE=1 to skip the pause.
if defined EYE_PROTECT_NO_PAUSE exit /b %RC%
echo %cmdcmdline% | "%SystemRoot%\System32\findstr.exe" /i /c:"%~nx0" >nul
if errorlevel 1 exit /b %RC%

echo Press any key to close this window . . .
pause >nul
exit /b %RC%
