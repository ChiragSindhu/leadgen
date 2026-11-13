@echo off
cd /d %~dp0
start "Dashboard" cmd /k python -m streamlit run app.py
start "Telegram bot" cmd /k python bot.py
