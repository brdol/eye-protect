@echo off
REM EyeProtect - restart / apply config (double-click to run)
setlocal
cd /d "%~dp0"

call "%~dp0_find_python.bat"

%PY% "%~dp0restart_service.py"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo [FAILED] exit code %RC%
    if "%RC%"=="9009" (
        echo [HINT] Python not found. Install Python or add it to PATH.
    ) else (
        echo [HINT] Python failed to start. Set EYE_PROTECT_PYTHON to a full python.exe path if needed.
    )
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
