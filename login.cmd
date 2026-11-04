@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Вход в Telegram для SenderX
echo   Введите номер телефона, затем код из Telegram.
echo   Ввод кода и пароля 2FA не отображается на экране.
echo ============================================
echo.
".venv\Scripts\python.exe" auth_login.py
echo.
echo ---------- ГОТОВО ----------
pause
