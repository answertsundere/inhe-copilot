@echo off
chcp 65001 >nul 2>&1
title INHE Copilot - QianNiu Sidecar

cd /d "%~dp0"

:: Load config from sidecar.env
for /f "usebackq tokens=1,* delims==" %%a in ("sidecar.env") do (
    set "line=%%a"
    if not "!line:~0,1!"=="#" (
        set "%%a=%%b"
    )
)

echo ============================================
echo  INHE Copilot - QianNiu Sidecar
echo  VLM: %SIDECAR_VISION_MODEL%
echo  Backend: %COPILOT_BACKEND%
echo  Auto-Analyze: ON
echo ============================================
echo.

python scripts\sidecar\qianniu_sidecar.py --auto-analyze --vision-provider custom --stable-reads 1

pause
