@echo off
call venv\Scripts\activate
set PORT=3001
python src\server.py
pause
