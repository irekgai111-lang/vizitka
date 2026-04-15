@echo off
chcp 65001 >nul
echo ========================================
echo   BOT BUSINESS — Запуск бота
echo ========================================
echo.

cd /d "%~dp0bot"

if not exist ".env" (
    echo [!] Файл .env не найден!
    echo.
    echo Создай файл .env в папке bot\ со следующим содержимым:
    echo.
    echo   BOT_TOKEN=токен_от_BotFather
    echo   ADMIN_ID=твой_telegram_id
    echo.
    echo Как получить:
    echo   1. Открой Telegram — найди @BotFather — напиши /newbot
    echo   2. Скопируй токен в .env
    echo   3. Найди @userinfobot — он покажет твой ID
    echo.
    pause
    exit
)

echo [1/2] Устанавливаю зависимости...
pip install -r requirements.txt >nul 2>&1

echo [2/2] Запускаю бота...
echo.
echo Бот работает! Не закрывай это окно.
echo Чтобы остановить — нажми Ctrl+C
echo.
python bot.py

pause
