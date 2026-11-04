@echo off
REM Resolve a usable Python launcher into the PY variable.
REM Caller must NOT rely on setlocal isolation here (we intentionally set PY in the caller's scope).
REM Priority: EYE_PROTECT_PYTHON > py launcher > registry PythonCore (3.x) > where python (skip Store stub) > python
set "PY="

if defined EYE_PROTECT_PYTHON set "PY=%EYE_PROTECT_PYTHON%"
if defined PY exit /b 0

where py >nul 2>nul && (
    set "PY=py -3"
    exit /b 0
)

REM Standard Windows Python registration (works without PATH, e.g. conda / python.org installs).
for %%R in ("HKLM\SOFTWARE\Python\PythonCore" "HKCU\SOFTWARE\Python\PythonCore" "HKLM\SOFTWARE\WOW6432Node\Python\PythonCore") do (
    for /f "usebackq delims=" %%K in (`reg query %%R 2^>nul`) do (
        if not defined PY (
            echo %%K|"%SystemRoot%\System32\findstr.exe" /c:"\3." >nul
            if not errorlevel 1 (
                for /f "tokens=2,*" %%A in ('reg query "%%K\InstallPath" /ve 2^>nul ^| "%SystemRoot%\System32\findstr.exe" /i "REG_SZ"') do (
                    if not defined PY if exist "%%B\python.exe" set "PY=%%B\python.exe"
                )
            )
        )
    )
)
if defined PY exit /b 0

REM Fall back to PATH, but skip the Microsoft Store alias (it is not a real interpreter).
for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PY (
        echo %%P|"%SystemRoot%\System32\findstr.exe" /i /c:"\WindowsApps\" >nul
        if errorlevel 1 set "PY=%%P"
    )
)
if defined PY exit /b 0

REM Last resort: let the failure surface with a clear exit code (9009).
set "PY=python"
exit /b 0
