@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   Панель «Почтамт» — не закрывайте это окно
echo   Адрес: http://<IP этого ПК>:8765   пароль в .env (PANEL_PASSWORD)
echo ============================================================
".venv\Scripts\python.exe" -m panel.app
pause
