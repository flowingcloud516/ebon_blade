@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m frostmourne %*
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        python -m frostmourne %*
    ) else (
        py -3 -m frostmourne %*
    )
)
if errorlevel 1 pause
