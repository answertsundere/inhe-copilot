@echo off
chcp 65001 >nul
cd /d "%~dp0\..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\sidecar\install_sidecar_client.ps1"
pause
