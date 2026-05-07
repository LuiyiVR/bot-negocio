@echo off
echo Instalando / actualizando dependencias...
pip install --upgrade python-telegram-bot==21.10 python-dotenv
echo.
echo Iniciando bot...
python bot.py
pause
