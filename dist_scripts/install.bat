@echo off
REM EyeProtect - install in the current folder (double-click to run)
setlocal
cd /d "%~dp0"

if not exist "%~dp0python\python.exe" (
    echo [FAIL] python\python.exe not found. Please extract the complete package.
    set "RC=1"
    goto :done
)

if not exist "%~dp0config.json" if exist "%~dp0config.example.json" copy /y "%~dp0config.example.json" "%~dp0config.json" >nul

"%~dp0python\python.exe" "%~dp0eye_protect.py" --install
set "RC=%ERRORLEVEL%"

:done
if not "%RC%"=="0" (echo [FAILED] exit code %RC%) else (echo [DONE])
call :pause_if_double_click
exit /b %RC%

:pause_if_double_click
if defined EYE_PROTECT_NO_PAUSE exit /b 0
echo %cmdcmdline% | "%SystemRoot%\System32\findstr.exe" /i /c:"%~nx0" >nul
if errorlevel 1 exit /b 0
echo.
echo Press any key to close this window . . .
pause >nul
exit /b 0
