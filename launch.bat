@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m ebon_blade %*
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        python -m ebon_blade %*
    ) else (
        py -3 -m ebon_blade %*
    )
)
if errorlevel 1 pause
