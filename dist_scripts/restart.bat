@echo off
REM EyeProtect - restart (apply config changes) (double-click to run)
setlocal
cd /d "%~dp0"
"%~dp0python\python.exe" "%~dp0eye_protect.py" --restart
set "RC=%ERRORLEVEL%"
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
