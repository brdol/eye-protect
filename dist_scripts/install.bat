@echo off
REM EyeProtect - install to %LOCALAPPDATA%\EyeProtect (double-click to run)
setlocal
set "SRC=%~dp0"
set "DST=%LOCALAPPDATA%\EyeProtect"

if /i "%SRC%"=="%DST%\" goto :copied
echo Installing to %DST% ...
"%SystemRoot%\System32\robocopy.exe" "%SRC%." "%DST%" /MIR /XD "%DST%\logs" /XF config.json >nul
:copied

if not exist "%DST%\config.json" if exist "%DST%\config.example.json" copy /y "%DST%\config.example.json" "%DST%\config.json" >nul

"%DST%\EyeProtect.exe" --install
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
