@echo off
start "" "D:\tor\tor\tor.exe" -f "D:\tor\tor\torrc"
timeout /t 30
cd /d D:\Projects\books
call .venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000