import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-change-this-secret')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', f"sqlite:///{BASE_DIR / 'instance' / 'scorm_classroom.db'}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_UPLOAD_MB', '300')) * 1024 * 1024
    UPLOAD_ROOT = Path(os.getenv('UPLOAD_ROOT', str(BASE_DIR / 'uploads' / 'scorm')))
    BASE_URL = os.getenv('BASE_URL', 'http://localhost:5000').rstrip('/')
    LOCAL_TIMEZONE = os.getenv('LOCAL_TIMEZONE', 'Atlantic/Canary')

    # Acceso local del profesorado. El alumnado usa enlace/código/PIN y no Google.
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', '')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')

    # Integración Google opcional y separada.
    GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
    GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', f"{BASE_URL}/auth/google/callback")
    TOKEN_ENCRYPTION_KEY = os.getenv('TOKEN_ENCRYPTION_KEY', '')
    CLASSROOM_ENABLED = os.getenv('CLASSROOM_ENABLED', 'false').lower() == 'true'
    DEV_AUTH = os.getenv('DEV_AUTH', 'true').lower() == 'true'

    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
    PREFERRED_URL_SCHEME = 'https' if BASE_URL.startswith('https://') else 'http'
