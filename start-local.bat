@echo off
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
set DEV_AUTH=true
set CLASSROOM_ENABLED=false
set BASE_URL=http://localhost:5000
set SESSION_COOKIE_SECURE=false
set SESSION_COOKIE_SAMESITE=Lax
python app.py
