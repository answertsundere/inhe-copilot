@echo off
cd /d "D:\桌面文件\客服\copilot"
set COPILOT_WEB_PORT=5012
start "INHE Copilot 5012" "C:\Users\sshuser\AppData\Local\Programs\Python\Python311\pythonw.exe" run_prod.py
