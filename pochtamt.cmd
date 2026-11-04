@echo off
cd /d "%~dp0"
start "Почтамт — панель" cmd /k run_panel.cmd
timeout /t 3 >nul
start "Почтамт — воркер" cmd /k run_worker.cmd
start "" http://127.0.0.1:8765
