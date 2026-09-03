#!/usr/bin/env bash
set -e
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DEV_AUTH=true
export CLASSROOM_ENABLED=false
export BASE_URL=http://localhost:5000
export SESSION_COOKIE_SECURE=false
export SESSION_COOKIE_SAMESITE=Lax
python app.py
