from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for
)
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from models import db, User, Package, Attachment, Assignment, Attempt, Event, Course, CourseItem, CourseEnrollment
from security import encrypt_text
from scorm_manifest import import_scorm_zip
from classroom_api import TEACHER_SCOPE, STUDENT_SCOPE, create_attachment, get_addon_context, pass_grade


def now_utc():
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    if str(app.config['SQLALCHEMY_DATABASE_URI']).startswith('sqlite:'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'timeout': 30}}
    app.config['UPLOAD_ROOT'].mkdir(parents=True, exist_ok=True)
    (Path(__file__).parent / 'instance').mkdir(exist_ok=True)
    db.init_app(app)

    def migrate_sqlite_legacy_schema():
        """Actualización ligera para instalaciones SQLite de la versión MVP anterior."""
        if db.engine.dialect.name != 'sqlite':
            return
        user_columns = {
            'username': 'VARCHAR(128)',
            'password_hash': 'VARCHAR(255)',
            'pin_hash': 'VARCHAR(255)',
            'student_code': 'VARCHAR(64)',
            'access_token': 'VARCHAR(128)',
            'group_name': 'VARCHAR(128)',
            'active': 'BOOLEAN DEFAULT 1',
            'archived': 'BOOLEAN DEFAULT 0',
        }
        attempt_columns = {'assignment_id': 'INTEGER', 'course_item_id': 'INTEGER'}
        with db.engine.begin() as conn:
            conn.execute(text('PRAGMA journal_mode=WAL'))
            conn.execute(text('PRAGMA synchronous=NORMAL'))
            tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            if 'user' in tables:
                existing = {r[1] for r in conn.execute(text('PRAGMA table_info(user)'))}
                for name, sql_type in user_columns.items():
                    if name not in existing:
                        conn.execute(text(f'ALTER TABLE user ADD COLUMN {name} {sql_type}'))
            if 'attempt' in tables:
                existing = {r[1] for r in conn.execute(text('PRAGMA table_info(attempt)'))}
                for name, sql_type in attempt_columns.items():
                    if name not in existing:
                        conn.execute(text(f'ALTER TABLE attempt ADD COLUMN {name} {sql_type}'))

    with app.app_context():
        db.create_all()
        migrate_sqlite_legacy_schema()
        # create_all de nuevo permite crear tablas nuevas aunque se parta de una base antigua.
        db.create_all()

        username = (app.config['ADMIN_USERNAME'] or '').strip()
        password = app.config['ADMIN_PASSWORD'] or ''
        if username and password:
            admin = User.query.filter_by(username=username).first()
            if not admin:
                email = username if '@' in username else f'{username}@local.invalid'
                admin = User.query.filter_by(email=email).first()
            if not admin:
                admin = User(email=email, name='Administrador SCORM', role='teacher', username=username)
                db.session.add(admin)
            admin.username = username
            admin.role = 'teacher'
            admin.active = True
            # La contraseña de entorno es la fuente de verdad en despliegue Docker.
            if not admin.password_hash or not check_password_hash(admin.password_hash, password):
                admin.password_hash = generate_password_hash(password)
            db.session.commit()

    @app.after_request
    def security_headers(response):
        response.headers['Content-Security-Policy'] = (
            "frame-ancestors 'self' https://classroom.google.com https://*.google.com; "
            "object-src 'none'; base-uri 'self'"
        )
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def current_user():
        uid = session.get('user_id')
        user = db.session.get(User, uid) if uid else None
        if user and (user.active is False or getattr(user, 'archived', False)):
            session.clear()
            return None
        return user

    def login_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user():
                session['return_to'] = request.url
                return redirect(url_for('login'))
            return fn(*args, **kwargs)
        return wrapper

    def admin_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user or user.role != 'teacher':
                session['return_to'] = request.url
                return redirect(url_for('admin_login'))
            return fn(*args, **kwargs)
        return wrapper

    def student_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user or user.role != 'student':
                return redirect(url_for('student_access'))
            return fn(*args, **kwargs)
        return wrapper

    def public_link(endpoint, **values):
        return app.config['BASE_URL'] + url_for(endpoint, **values)

    def make_token():
        return secrets.token_urlsafe(24)

    def make_student_code(group_name=''):
        prefix = re.sub(r'[^A-Z0-9]', '', (group_name or '').upper())[:5] or 'AL'
        for _ in range(100):
            suffix = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
            code = f'{prefix}-{suffix}'
            if not User.query.filter_by(student_code=code).first():
                return code
        return f'AL-{secrets.token_hex(6).upper()}'

    def unique_student_token():
        while True:
            token = make_token()
            if not User.query.filter_by(access_token=token).first():
                return token

    def unique_assignment_token():
        while True:
            token = make_token()
            if not Assignment.query.filter_by(token=token).first():
                return token

    def synthetic_email():
        return f'student-{secrets.token_hex(12)}@local.invalid'

    def validate_pin(pin):
        return bool(re.fullmatch(r'\d{4,12}', pin or ''))

    def verify_pin(user, pin):
        if not user.pin_hash:
            return True
        return bool(pin and check_password_hash(user.pin_hash, pin))

    def parse_local_datetime(raw):
        raw = (raw or '').strip()
        if not raw:
            return None
        try:
            naive = datetime.fromisoformat(raw)
            return naive.replace(tzinfo=ZoneInfo(app.config['LOCAL_TIMEZONE'])).astimezone(timezone.utc)
        except (ValueError, TypeError):
            raise ValueError('Fecha u hora no válida.')

    def local_datetime(value):
        if not value:
            return '—'
        return as_utc(value).astimezone(ZoneInfo(app.config['LOCAL_TIMEZONE'])).strftime('%d/%m/%Y %H:%M')

    app.jinja_env.filters['localdt'] = local_datetime

    def assignment_effective_max_attempts(assignment):
        if assignment.max_attempts is not None:
            return assignment.max_attempts
        return assignment.package.max_attempts

    def assignment_effective_fullscreen(assignment):
        return assignment.fullscreen if assignment.fullscreen is not None else assignment.package.fullscreen

    def assignment_effective_focus_limit(assignment):
        return assignment.focus_limit if assignment.focus_limit is not None else assignment.package.focus_limit

    def assignment_time_status(assignment):
        now = now_utc()
        start = as_utc(assignment.available_from)
        deadline = as_utc(assignment.deadline)
        if not assignment.active:
            return False, 'Esta actividad está desactivada.'
        if start and now < start:
            return False, f'Estará disponible el {local_datetime(assignment.available_from)}.'
        if deadline and now > deadline:
            return False, f'El plazo finalizó el {local_datetime(assignment.deadline)}.'
        return True, None

    def package_unlocked(package, user):
        if not package.prerequisite_id:
            return True, None
        prior = Attempt.query.filter_by(package_id=package.prerequisite_id, user_id=user.id).order_by(Attempt.id.desc()).first()
        if not prior or prior.status not in ('completed', 'passed'):
            return False, 'Debes completar la actividad anterior.'
        prereq = db.session.get(Package, package.prerequisite_id)
        if prereq and prior.score is not None and prior.score < prereq.pass_score:
            return False, f'Debes obtener al menos {prereq.pass_score:g}% en la actividad anterior.'
        return True, None

    def get_or_create_attempt(package, user, attachment=None, submission_id=None, assignment=None, course_item=None):
        query = Attempt.query.filter_by(package_id=package.id, user_id=user.id)
        if attachment:
            query = query.filter_by(attachment_id=attachment.id)
        if assignment:
            query = query.filter_by(assignment_id=assignment.id)
        if course_item:
            query = query.filter_by(course_item_id=course_item.id)
        attempt = query.order_by(Attempt.id.desc()).first()
        if attempt and attempt.status not in ('completed', 'passed', 'failed'):
            if submission_id and not attempt.submission_id:
                attempt.submission_id = submission_id
                db.session.commit()
            return attempt

        max_attempts = assignment_effective_max_attempts(assignment) if assignment else package.max_attempts
        completed_count = query.count()
        if max_attempts and completed_count >= max_attempts:
            abort(403, description='Se ha alcanzado el número máximo de intentos.')
        attempt = Attempt(
            package_id=package.id,
            user_id=user.id,
            attachment_id=attachment.id if attachment else None,
            assignment_id=assignment.id if assignment else None,
            course_item_id=course_item.id if course_item else None,
            submission_id=submission_id,
        )
        db.session.add(attempt)
        db.session.commit()
        return attempt

    def assignment_view_status(assignment):
        available, reason = assignment_time_status(assignment)
        attempts = Attempt.query.filter_by(assignment_id=assignment.id).order_by(Attempt.id.desc()).all()
        latest = attempts[0] if attempts else None
        if latest and latest.status in ('passed', 'completed'):
            return 'Finalizada', 'ok', latest, len(attempts)
        max_attempts = assignment_effective_max_attempts(assignment)
        if latest and latest.status == 'failed' and max_attempts and len(attempts) >= max_attempts:
            return 'Intentos agotados', 'danger', latest, len(attempts)
        if latest and latest.status not in ('completed', 'passed', 'failed'):
            return 'En progreso', 'warn', latest, len(attempts)
        if not available:
            if assignment.available_from and now_utc() < as_utc(assignment.available_from):
                return 'Próximamente', 'muted', latest, len(attempts)
            return 'Fuera de plazo', 'danger', latest, len(attempts)
        return 'Disponible', 'info', latest, len(attempts)

    def course_item_attempt(item, student):
        return Attempt.query.filter_by(course_item_id=item.id, user_id=student.id).order_by(Attempt.id.desc()).first()

    def course_item_is_complete(item, student):
        attempt = course_item_attempt(item, student)
        if not attempt:
            return False, False, None
        complete = attempt.status in ('completed', 'passed')
        threshold = item.min_score if item.min_score is not None else item.package.pass_score
        passed = attempt.status == 'passed' or (attempt.score is not None and attempt.score >= threshold)
        if not item.require_pass:
            passed = complete
        return complete, passed, attempt

    def course_item_unlocked(course, item, student):
        if not course.sequential:
            return True, None
        prior_items = [i for i in course.items if i.position < item.position and i.required]
        for prior in prior_items:
            complete, passed, _attempt = course_item_is_complete(prior, student)
            if not complete:
                return False, f'Debes completar primero: {prior.title or prior.package.title}.'
            if prior.require_pass and not passed:
                threshold = prior.min_score if prior.min_score is not None else prior.package.pass_score
                return False, f'Debes superar {prior.title or prior.package.title} con al menos {threshold:g}%.'
        return True, None

    def course_progress(course, student):
        required = [i for i in course.items if i.required]
        if not required:
            return 0, 0, 0.0
        completed = 0
        for item in required:
            complete, passed, _attempt = course_item_is_complete(item, student)
            if complete and (passed or not item.require_pass):
                completed += 1
        return completed, len(required), round((completed / len(required)) * 100, 1)

    def delete_student_permanently(student):
        """Elimina al alumno y sus datos dependientes sin afectar a paquetes ni cursos."""
        attempt_ids = [row[0] for row in db.session.query(Attempt.id).filter_by(user_id=student.id).all()]
        if attempt_ids:
            Event.query.filter(Event.attempt_id.in_(attempt_ids)).delete(synchronize_session=False)
        Attempt.query.filter_by(user_id=student.id).delete(synchronize_session=False)
        Assignment.query.filter_by(student_id=student.id).delete(synchronize_session=False)
        CourseEnrollment.query.filter_by(student_id=student.id).delete(synchronize_session=False)
        db.session.delete(student)

    def assignment_link(assignment):
        endpoint = 'exam_access' if assignment.mode == 'exam' else 'activity_access'
        return public_link(endpoint, token=assignment.token)

    def browser_device_digest(device_id):
        key = app.config['SECRET_KEY'].encode('utf-8')
        return hashlib.sha256(key + b':' + device_id.encode('utf-8')).hexdigest()

    @app.context_processor
    def inject_globals():
        return {
            'current_user': current_user(),
            'public_link': public_link,
            'assignment_link': assignment_link,
            'classroom_enabled': app.config['CLASSROOM_ENABLED'],
        }

    # ------------------------------------------------------------------
    # Portada y autenticación
    # ------------------------------------------------------------------
    @app.get('/health')
    def health():
        return jsonify({'ok': True, 'version': '3.0.0-lms'})

    @app.get('/')
    def index():
        return render_template('index.html', packages=Package.query.order_by(Package.created_at.desc()).limit(6).all())

    @app.get('/login')
    def login():
        return render_template('login.html')

    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if request.method == 'GET':
            return render_template('admin_login.html')
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = User.query.filter_by(username=username, role='teacher').first()
        if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
            flash('Usuario o contraseña incorrectos.', 'error')
            return redirect(url_for('admin_login'))
        target = session.get('return_to') or url_for('admin_dashboard')
        session.clear()
        session['user_id'] = user.id
        return redirect(target)

    @app.get('/dev/login/<role>')
    def dev_login(role):
        if not app.config['DEV_AUTH']:
            abort(404)
        role = 'teacher' if role == 'teacher' else 'student'
        email = f'{role}@local.test'
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, name=f'{role.title()} de prueba', role=role, access_token=unique_student_token() if role == 'student' else None)
            if role == 'student':
                user.student_code = make_student_code('DEV')
            db.session.add(user)
            db.session.commit()
        session['user_id'] = user.id
        target = session.pop('return_to', None) or (url_for('admin_dashboard') if role == 'teacher' else url_for('student_dashboard'))
        return redirect(target)

    @app.get('/auth/google')
    def google_login():
        if not app.config['GOOGLE_CLIENT_ID'] or not app.config['GOOGLE_CLIENT_SECRET']:
            abort(503, description='Google OAuth todavía no está configurado.')
        session['return_to'] = request.args.get('return_to') or session.get('return_to') or url_for('library')
        client_config = {
            'web': {
                'client_id': app.config['GOOGLE_CLIENT_ID'],
                'client_secret': app.config['GOOGLE_CLIENT_SECRET'],
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [app.config['GOOGLE_REDIRECT_URI']],
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=['openid', 'email', 'profile', TEACHER_SCOPE, STUDENT_SCOPE],
            redirect_uri=app.config['GOOGLE_REDIRECT_URI'],
        )
        auth_url, state = flow.authorization_url(
            access_type='offline', include_granted_scopes='true', prompt='consent',
            login_hint=request.args.get('login_hint') or None,
        )
        session['oauth_state'] = state
        return redirect(auth_url)

    @app.get('/auth/google/callback')
    def google_callback():
        state = session.get('oauth_state')
        client_config = {
            'web': {
                'client_id': app.config['GOOGLE_CLIENT_ID'],
                'client_secret': app.config['GOOGLE_CLIENT_SECRET'],
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [app.config['GOOGLE_REDIRECT_URI']],
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=['openid', 'email', 'profile', TEACHER_SCOPE, STUDENT_SCOPE],
            state=state, redirect_uri=app.config['GOOGLE_REDIRECT_URI'],
        )
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        claims = id_token.verify_oauth2_token(creds.id_token, google_requests.Request(), app.config['GOOGLE_CLIENT_ID'])
        sub, email, name = claims['sub'], claims['email'], claims.get('name') or claims['email']
        user = User.query.filter((User.google_sub == sub) | (User.email == email)).first()
        if not user:
            user = User(google_sub=sub, email=email, name=name, role='student')
            db.session.add(user)
        user.google_sub = sub
        user.name = name
        if creds.refresh_token:
            user.refresh_token_enc = encrypt_text(creds.refresh_token, app.config['TOKEN_ENCRYPTION_KEY'])
        db.session.commit()
        session['user_id'] = user.id
        return redirect(session.pop('return_to', None) or url_for('library'))

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))

    # ------------------------------------------------------------------
    # Acceso autónomo del alumnado: código, enlace personal y asignación
    # ------------------------------------------------------------------
    @app.route('/student/access', methods=['GET', 'POST'])
    def student_access():
        if request.method == 'GET':
            return render_template('student_access.html')
        code = (request.form.get('code') or '').strip().upper()
        pin = (request.form.get('pin') or '').strip()
        user = User.query.filter_by(student_code=code, role='student').first()
        if not user or user.active is False or getattr(user, 'archived', False) or not verify_pin(user, pin):
            flash('Código o PIN incorrectos.', 'error')
            return redirect(url_for('student_access'))
        session.clear()
        session['user_id'] = user.id
        if user.pin_hash:
            session['student_pin_verified'] = user.id
        return redirect(url_for('student_dashboard'))

    @app.route('/u/<token>', methods=['GET', 'POST'])
    def student_personal(token):
        user = User.query.filter_by(access_token=token, role='student').first()
        if not user or user.active is False or getattr(user, 'archived', False):
            abort(404, description='Enlace personal no válido.')
        already_verified = session.get('user_id') == user.id and (not user.pin_hash or session.get('student_pin_verified') == user.id)
        if user.pin_hash and not already_verified:
            if request.method == 'GET':
                return render_template('personal_access.html', student=user)
            pin = (request.form.get('pin') or '').strip()
            if not verify_pin(user, pin):
                flash('PIN incorrecto.', 'error')
                return redirect(url_for('student_personal', token=token))
        session.clear()
        session['user_id'] = user.id
        if user.pin_hash:
            session['student_pin_verified'] = user.id
        return redirect(url_for('student_dashboard'))

    @app.get('/student')
    @student_required
    def student_dashboard():
        user = current_user()
        assignments = Assignment.query.filter_by(student_id=user.id, active=True).order_by(Assignment.created_at.desc()).all()
        rows = []
        for assignment in assignments:
            label, badge, latest, count = assignment_view_status(assignment)
            rows.append({
                'assignment': assignment, 'label': label, 'badge': badge,
                'latest': latest, 'attempt_count': count,
                'max_attempts': assignment_effective_max_attempts(assignment),
            })
        enrollments = CourseEnrollment.query.filter_by(student_id=user.id, active=True).all()
        course_rows = []
        for enrollment in enrollments:
            if not enrollment.course.active:
                continue
            completed, total, progress = course_progress(enrollment.course, user)
            course_rows.append({
                'course': enrollment.course, 'completed': completed,
                'total': total, 'progress': progress,
            })
        course_rows.sort(key=lambda r: r['course'].title.lower())
        return render_template('student_dashboard.html', student=user, rows=rows, course_rows=course_rows)

    @app.get('/student/courses/<int:course_id>')
    @student_required
    def student_course(course_id):
        user = current_user()
        enrollment = CourseEnrollment.query.filter_by(course_id=course_id, student_id=user.id, active=True).first()
        if not enrollment or not enrollment.course.active:
            abort(404, description='No estás matriculado en este curso.')
        course = enrollment.course
        item_rows = []
        for item in course.items:
            unlocked, reason = course_item_unlocked(course, item, user)
            complete, passed, attempt = course_item_is_complete(item, user)
            if passed:
                label, badge = 'Superada', 'ok'
            elif complete:
                label, badge = 'Completada', 'warn'
            elif attempt:
                label, badge = 'En progreso', 'warn'
            elif unlocked:
                label, badge = 'Disponible', 'info'
            else:
                label, badge = 'Bloqueada', 'muted'
            item_rows.append({
                'item': item, 'unlocked': unlocked, 'reason': reason,
                'complete': complete, 'passed': passed, 'attempt': attempt,
                'label': label, 'badge': badge,
            })
        completed, total, progress = course_progress(course, user)
        return render_template(
            'student_course.html', course=course, item_rows=item_rows,
            completed=completed, total=total, progress=progress,
        )

    @app.get('/student/courses/<int:course_id>/lessons/<int:item_id>/launch')
    @student_required
    def student_course_lesson_launch(course_id, item_id):
        user = current_user()
        enrollment = CourseEnrollment.query.filter_by(course_id=course_id, student_id=user.id, active=True).first()
        if not enrollment or not enrollment.course.active:
            abort(404, description='No estás matriculado en este curso.')
        item = CourseItem.query.filter_by(id=item_id, course_id=course_id).first_or_404()
        unlocked, reason = course_item_unlocked(enrollment.course, item, user)
        if not unlocked:
            abort(403, description=reason)
        attempt = get_or_create_attempt(item.package, user, course_item=item)
        return redirect(url_for('player', attempt_id=attempt.id))

    def assignment_access_impl(token, expected_mode):
        assignment = Assignment.query.filter_by(token=token).first()
        if not assignment or not assignment.active:
            abort(404, description='Enlace de actividad no válido.')
        if assignment.mode != expected_mode:
            return redirect(url_for('exam_access' if assignment.mode == 'exam' else 'activity_access', token=assignment.token))
        student = assignment.student
        if not student or student.active is False or getattr(student, 'archived', False):
            abort(403, description='El acceso de este alumno está desactivado.')
        available, reason = assignment_time_status(assignment)
        pin_verified = session.get('user_id') == student.id and (not assignment.require_pin or session.get('student_pin_verified') == student.id)

        if request.method == 'GET':
            return render_template(
                'assignment_access.html', assignment=assignment, student=student,
                available=available, reason=reason, pin_verified=pin_verified,
                max_attempts=assignment_effective_max_attempts(assignment),
            )

        if not available:
            abort(403, description=reason)
        if assignment.require_pin and not pin_verified:
            pin = (request.form.get('pin') or '').strip()
            if not verify_pin(student, pin):
                flash('PIN incorrecto.', 'error')
                return redirect(request.url)

        unlocked, unlock_reason = package_unlocked(assignment.package, student)
        if not unlocked:
            abort(403, description=unlock_reason)

        device_id = request.cookies.get('scorm_device_id')
        new_device = False
        if not device_id:
            device_id = secrets.token_urlsafe(24)
            new_device = True
        if assignment.device_lock:
            digest = browser_device_digest(device_id)
            if assignment.device_hash and not secrets.compare_digest(assignment.device_hash, digest):
                abort(403, description='Este acceso está vinculado a otro dispositivo. El profesor debe restablecer el dispositivo desde el panel.')
            if not assignment.device_hash:
                assignment.device_hash = digest
                db.session.commit()

        session.clear()
        session['user_id'] = student.id
        if student.pin_hash and (assignment.require_pin or pin_verified):
            session['student_pin_verified'] = student.id

        attempt = get_or_create_attempt(assignment.package, student, assignment=assignment)
        response = redirect(url_for('player', attempt_id=attempt.id))
        if new_device:
            response.set_cookie(
                'scorm_device_id', device_id, max_age=31536000, httponly=True,
                secure=app.config['SESSION_COOKIE_SECURE'], samesite='Lax'
            )
        return response

    @app.route('/a/<token>', methods=['GET', 'POST'])
    def activity_access(token):
        return assignment_access_impl(token, 'activity')

    @app.route('/e/<token>', methods=['GET', 'POST'])
    def exam_access(token):
        return assignment_access_impl(token, 'exam')

    # ------------------------------------------------------------------
    # Administración local
    # ------------------------------------------------------------------
    @app.get('/admin')
    @admin_required
    def admin_dashboard():
        student_count = User.query.filter_by(role='student').count()
        package_count = Package.query.count()
        assignment_count = Assignment.query.filter_by(active=True).count()
        attempt_count = Attempt.query.count()
        recent = Attempt.query.order_by(Attempt.updated_at.desc()).limit(20).all()
        return render_template(
            'admin_dashboard.html', student_count=student_count, package_count=package_count,
            assignment_count=assignment_count, attempt_count=attempt_count, recent=recent,
        )

    @app.route('/admin/students', methods=['GET', 'POST'])
    @admin_required
    def admin_students():
        if request.method == 'POST':
            name = (request.form.get('name') or '').strip()
            group_name = (request.form.get('group_name') or '').strip()
            email = (request.form.get('email') or '').strip() or synthetic_email()
            pin = (request.form.get('pin') or '').strip()
            code = (request.form.get('student_code') or '').strip().upper() or make_student_code(group_name)
            if not name:
                flash('Debes indicar el nombre del alumno.', 'error')
            elif pin and not validate_pin(pin):
                flash('El PIN debe contener entre 4 y 12 cifras.', 'error')
            elif User.query.filter_by(student_code=code).first():
                flash('Ese código de alumno ya existe.', 'error')
            elif User.query.filter_by(email=email).first():
                flash('Ese correo ya está registrado.', 'error')
            else:
                student = User(
                    email=email, name=name, role='student', group_name=group_name,
                    student_code=code, access_token=unique_student_token(), active=True,
                    pin_hash=generate_password_hash(pin) if pin else None,
                )
                db.session.add(student)
                db.session.commit()
                flash(f'Alumno creado. Código: {student.student_code}' + (f' · PIN: {pin}' if pin else ''), 'success')
            return redirect(url_for('admin_students'))
        students = User.query.filter_by(role='student').order_by(User.group_name, User.name).all()
        return render_template('admin_students.html', students=students)

    @app.post('/admin/students/import')
    @admin_required
    def admin_students_import():
        uploaded = request.files.get('csv_file')
        if not uploaded:
            flash('Selecciona un archivo CSV.', 'error')
            return redirect(url_for('admin_students'))
        try:
            raw = uploaded.read().decode('utf-8-sig')
            try:
                dialect = csv.Sniffer().sniff(raw[:4096], delimiters=',;\t')
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
            created = 0
            skipped = 0
            for row in reader:
                norm = {(k or '').strip().lower(): (v or '').strip() for k, v in row.items()}
                name = norm.get('nombre') or norm.get('name') or norm.get('alumno') or ''
                group_name = norm.get('grupo') or norm.get('group') or ''
                email = norm.get('email') or norm.get('correo') or synthetic_email()
                pin = norm.get('pin') or ''
                code = (norm.get('identificador') or norm.get('codigo') or norm.get('código') or '').upper()
                if not name or (pin and not validate_pin(pin)):
                    skipped += 1
                    continue
                if code and User.query.filter_by(student_code=code).first():
                    skipped += 1
                    continue
                if email and User.query.filter_by(email=email).first():
                    skipped += 1
                    continue
                student = User(
                    email=email, name=name, role='student', group_name=group_name,
                    student_code=code or make_student_code(group_name),
                    access_token=unique_student_token(), active=True,
                    pin_hash=generate_password_hash(pin) if pin else None,
                )
                db.session.add(student)
                created += 1
            db.session.commit()
            flash(f'Importación finalizada: {created} alumnos creados; {skipped} filas omitidas.', 'success')
        except Exception as exc:
            db.session.rollback()
            flash(f'No se pudo importar el CSV: {exc}', 'error')
        return redirect(url_for('admin_students'))

    @app.post('/admin/students/<int:student_id>/pin')
    @admin_required
    def admin_student_pin(student_id):
        student = db.get_or_404(User, student_id)
        if student.role != 'student':
            abort(400)
        pin = (request.form.get('pin') or '').strip()
        if pin and not validate_pin(pin):
            flash('El PIN debe contener entre 4 y 12 cifras.', 'error')
        else:
            student.pin_hash = generate_password_hash(pin) if pin else None
            db.session.commit()
            flash('PIN actualizado.' if pin else 'PIN eliminado.', 'success')
        return redirect(url_for('admin_students'))

    @app.post('/admin/students/<int:student_id>/reset-link')
    @admin_required
    def admin_student_reset_link(student_id):
        student = db.get_or_404(User, student_id)
        student.access_token = unique_student_token()
        db.session.commit()
        flash('Enlace personal regenerado. El anterior deja de ser válido.', 'success')
        return redirect(url_for('admin_students'))

    @app.post('/admin/students/<int:student_id>/toggle')
    @admin_required
    def admin_student_toggle(student_id):
        student = db.get_or_404(User, student_id)
        if student.role != 'student':
            abort(400)
        if getattr(student, 'archived', False):
            student.archived = False
            student.active = True
        else:
            student.active = not bool(student.active)
        db.session.commit()
        flash('Estado del alumno actualizado.', 'success')
        return redirect(url_for('admin_students'))

    @app.route('/admin/students/<int:student_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def admin_student_edit(student_id):
        student = db.get_or_404(User, student_id)
        if student.role != 'student':
            abort(400)
        if request.method == 'GET':
            return render_template('admin_student_edit.html', student=student)
        name = (request.form.get('name') or '').strip()
        group_name = (request.form.get('group_name') or '').strip()
        email = (request.form.get('email') or '').strip() or student.email
        code = (request.form.get('student_code') or '').strip().upper()
        pin = (request.form.get('pin') or '').strip()
        if not name:
            flash('El nombre no puede quedar vacío.', 'error')
            return redirect(request.url)
        if pin and not validate_pin(pin):
            flash('El PIN debe contener entre 4 y 12 cifras.', 'error')
            return redirect(request.url)
        duplicate_code = User.query.filter(User.student_code == code, User.id != student.id).first() if code else None
        duplicate_email = User.query.filter(User.email == email, User.id != student.id).first() if email else None
        if duplicate_code:
            flash('Ese código de alumno ya está en uso.', 'error')
            return redirect(request.url)
        if duplicate_email:
            flash('Ese correo ya está registrado.', 'error')
            return redirect(request.url)
        student.name = name
        student.group_name = group_name
        student.email = email
        student.student_code = code or student.student_code or make_student_code(group_name)
        if pin:
            student.pin_hash = generate_password_hash(pin)
        if request.form.get('remove_pin'):
            student.pin_hash = None
        db.session.commit()
        flash('Datos del alumno actualizados.', 'success')
        return redirect(url_for('admin_students'))

    @app.post('/admin/students/<int:student_id>/archive')
    @admin_required
    def admin_student_archive(student_id):
        student = db.get_or_404(User, student_id)
        if student.role != 'student':
            abort(400)
        student.archived = True
        student.active = False
        db.session.commit()
        flash('Alumno archivado. Su historial se conserva.', 'success')
        return redirect(url_for('admin_students'))

    @app.post('/admin/students/<int:student_id>/restore')
    @admin_required
    def admin_student_restore(student_id):
        student = db.get_or_404(User, student_id)
        if student.role != 'student':
            abort(400)
        student.archived = False
        student.active = True
        db.session.commit()
        flash('Alumno restaurado y activado.', 'success')
        return redirect(url_for('admin_students'))

    @app.post('/admin/students/<int:student_id>/delete')
    @admin_required
    def admin_student_delete(student_id):
        student = db.get_or_404(User, student_id)
        if student.role != 'student':
            abort(400)
        if (request.form.get('confirmation') or '').strip().upper() != 'ELIMINAR':
            flash('Para borrar definitivamente escribe ELIMINAR en la confirmación.', 'error')
            return redirect(url_for('admin_student_edit', student_id=student.id))
        name = student.name
        delete_student_permanently(student)
        db.session.commit()
        flash(f'{name} y todo su historial han sido eliminados definitivamente.', 'success')
        return redirect(url_for('admin_students'))

    @app.post('/admin/students/bulk')
    @admin_required
    def admin_students_bulk():
        ids = {int(x) for x in request.form.getlist('student_ids') if x.isdigit()}
        students = User.query.filter(User.role == 'student', User.id.in_(ids)).all() if ids else []
        if not students:
            flash('Selecciona al menos un alumno.', 'error')
            return redirect(url_for('admin_students'))
        action = (request.form.get('bulk_action') or '').strip()
        if action == 'activate':
            for student in students:
                student.archived = False
                student.active = True
            message = f'{len(students)} alumnos activados.'
        elif action == 'deactivate':
            for student in students:
                student.active = False
            message = f'{len(students)} alumnos desactivados.'
        elif action == 'archive':
            for student in students:
                student.archived = True
                student.active = False
            message = f'{len(students)} alumnos archivados sin borrar su historial.'
        elif action == 'change_group':
            group_name = (request.form.get('bulk_group') or '').strip()
            for student in students:
                student.group_name = group_name
            message = f'Grupo actualizado para {len(students)} alumnos.'
        elif action == 'delete':
            if (request.form.get('bulk_confirmation') or '').strip().upper() != 'ELIMINAR':
                flash('La eliminación masiva requiere escribir ELIMINAR.', 'error')
                return redirect(url_for('admin_students'))
            for student in students:
                delete_student_permanently(student)
            message = f'{len(students)} alumnos eliminados definitivamente.'
        else:
            flash('Acción masiva no válida.', 'error')
            return redirect(url_for('admin_students'))
        db.session.commit()
        flash(message, 'success')
        return redirect(url_for('admin_students'))

    @app.route('/admin/assignments', methods=['GET', 'POST'])
    @admin_required
    def admin_assignments():
        packages = Package.query.order_by(Package.title).all()
        students = User.query.filter_by(role='student', active=True, archived=False).order_by(User.group_name, User.name).all()
        groups = sorted({s.group_name for s in students if s.group_name})

        if request.method == 'POST':
            package = db.session.get(Package, int(request.form.get('package_id') or 0))
            if not package:
                flash('Selecciona un paquete SCORM.', 'error')
                return redirect(url_for('admin_assignments'))
            selected_ids = {int(x) for x in request.form.getlist('student_ids') if x.isdigit()}
            group_name = (request.form.get('group_name') or '').strip()
            if group_name:
                selected_ids.update(s.id for s in students if s.group_name == group_name)
            selected = [s for s in students if s.id in selected_ids]
            if not selected:
                flash('Selecciona al menos un alumno o un grupo.', 'error')
                return redirect(url_for('admin_assignments'))

            mode = 'exam' if request.form.get('mode') == 'exam' else 'activity'
            try:
                available_from = parse_local_datetime(request.form.get('available_from'))
                deadline = parse_local_datetime(request.form.get('deadline'))
            except ValueError as exc:
                flash(str(exc), 'error')
                return redirect(url_for('admin_assignments'))
            if available_from and deadline and available_from >= deadline:
                flash('La fecha límite debe ser posterior al inicio.', 'error')
                return redirect(url_for('admin_assignments'))

            raw_attempts = (request.form.get('max_attempts') or '').strip()
            try:
                max_attempts = int(raw_attempts) if raw_attempts else (1 if mode == 'exam' else None)
                if max_attempts is not None and max_attempts < 0:
                    raise ValueError
            except ValueError:
                flash('El número de intentos no es válido.', 'error')
                return redirect(url_for('admin_assignments'))

            raw_focus = (request.form.get('focus_limit') or '').strip()
            try:
                focus_limit = int(raw_focus) if raw_focus else None
                if focus_limit is not None and focus_limit < 0:
                    raise ValueError
            except ValueError:
                flash('El límite de incidencias no es válido.', 'error')
                return redirect(url_for('admin_assignments'))

            require_pin = bool(request.form.get('require_pin'))
            device_lock = bool(request.form.get('device_lock')) or mode == 'exam'
            fullscreen = True if mode == 'exam' else None
            created = 0
            skipped = []
            for student in selected:
                if require_pin and not student.pin_hash:
                    skipped.append(student.name)
                    continue
                assignment = Assignment(
                    package_id=package.id, student_id=student.id, created_by=current_user().id,
                    token=unique_assignment_token(), mode=mode,
                    available_from=available_from, deadline=deadline,
                    max_attempts=max_attempts, require_pin=require_pin,
                    device_lock=device_lock, fullscreen=fullscreen,
                    focus_limit=focus_limit, active=True,
                )
                db.session.add(assignment)
                created += 1
            db.session.commit()
            message = f'Se han creado {created} asignaciones.'
            if skipped:
                message += ' Sin asignar por no tener PIN: ' + ', '.join(skipped[:8]) + ('…' if len(skipped) > 8 else '')
            flash(message, 'success' if created else 'error')
            return redirect(url_for('admin_assignments'))

        assignments = Assignment.query.order_by(Assignment.created_at.desc()).limit(500).all()
        return render_template('admin_assignments.html', packages=packages, students=students, groups=groups, assignments=assignments)

    @app.post('/admin/assignments/<int:assignment_id>/reset-device')
    @admin_required
    def admin_assignment_reset_device(assignment_id):
        assignment = db.get_or_404(Assignment, assignment_id)
        assignment.device_hash = None
        db.session.commit()
        flash('Vinculación de dispositivo restablecida.', 'success')
        return redirect(url_for('admin_assignments'))

    @app.post('/admin/assignments/<int:assignment_id>/toggle')
    @admin_required
    def admin_assignment_toggle(assignment_id):
        assignment = db.get_or_404(Assignment, assignment_id)
        assignment.active = not bool(assignment.active)
        db.session.commit()
        flash('Estado de la asignación actualizado.', 'success')
        return redirect(url_for('admin_assignments'))

    @app.get('/admin/results')
    @admin_required
    def admin_results():
        attempts = Attempt.query.order_by(Attempt.updated_at.desc()).limit(1000).all()
        return render_template('admin_results.html', attempts=attempts)

    # ------------------------------------------------------------------
    # Cursos / itinerarios de varias lecciones SCORM
    # ------------------------------------------------------------------
    @app.route('/admin/courses', methods=['GET', 'POST'])
    @admin_required
    def admin_courses():
        if request.method == 'POST':
            title = (request.form.get('title') or '').strip()
            if not title:
                flash('Indica el nombre del curso.', 'error')
                return redirect(url_for('admin_courses'))
            course = Course(
                title=title,
                description=(request.form.get('description') or '').strip() or None,
                sequential=bool(request.form.get('sequential')),
                active=True,
                created_by=current_user().id,
            )
            db.session.add(course)
            db.session.commit()
            flash('Curso creado. Añade ahora las lecciones SCORM.', 'success')
            return redirect(url_for('admin_course_detail', course_id=course.id))
        courses = Course.query.order_by(Course.created_at.desc()).all()
        return render_template('admin_courses.html', courses=courses)

    @app.get('/admin/courses/<int:course_id>')
    @admin_required
    def admin_course_detail(course_id):
        course = db.get_or_404(Course, course_id)
        packages = Package.query.order_by(Package.title).all()
        students = User.query.filter_by(role='student', active=True, archived=False).order_by(User.group_name, User.name).all()
        groups = sorted({s.group_name for s in students if s.group_name})
        enrollments = CourseEnrollment.query.filter_by(course_id=course.id, active=True).all()
        enrolled_ids = {e.student_id for e in enrollments}
        return render_template(
            'admin_course_detail.html', course=course, packages=packages, students=students,
            groups=groups, enrollments=enrollments, enrolled_ids=enrolled_ids,
        )

    @app.post('/admin/courses/<int:course_id>/settings')
    @admin_required
    def admin_course_settings(course_id):
        course = db.get_or_404(Course, course_id)
        title = (request.form.get('title') or '').strip()
        if not title:
            flash('El título no puede quedar vacío.', 'error')
            return redirect(url_for('admin_course_detail', course_id=course.id))
        course.title = title
        course.description = (request.form.get('description') or '').strip() or None
        course.sequential = bool(request.form.get('sequential'))
        course.active = bool(request.form.get('active'))
        db.session.commit()
        flash('Curso actualizado.', 'success')
        return redirect(url_for('admin_course_detail', course_id=course.id))

    @app.post('/admin/courses/<int:course_id>/items')
    @admin_required
    def admin_course_add_item(course_id):
        course = db.get_or_404(Course, course_id)
        package = db.session.get(Package, int(request.form.get('package_id') or 0))
        if not package:
            flash('Selecciona un SCORM.', 'error')
            return redirect(url_for('admin_course_detail', course_id=course.id))
        raw_score = (request.form.get('min_score') or '').strip()
        try:
            min_score = float(raw_score) if raw_score else None
            if min_score is not None and not (0 <= min_score <= 100):
                raise ValueError
        except ValueError:
            flash('La nota mínima debe estar entre 0 y 100.', 'error')
            return redirect(url_for('admin_course_detail', course_id=course.id))
        max_position = db.session.query(db.func.max(CourseItem.position)).filter_by(course_id=course.id).scalar() or 0
        item = CourseItem(
            course_id=course.id, package_id=package.id,
            title=(request.form.get('title') or '').strip() or None,
            position=max_position + 1,
            required=bool(request.form.get('required')),
            require_pass=bool(request.form.get('require_pass')),
            min_score=min_score,
        )
        db.session.add(item)
        db.session.commit()
        flash('Lección añadida al itinerario.', 'success')
        return redirect(url_for('admin_course_detail', course_id=course.id))

    @app.post('/admin/courses/<int:course_id>/items/<int:item_id>/update')
    @admin_required
    def admin_course_update_item(course_id, item_id):
        item = CourseItem.query.filter_by(id=item_id, course_id=course_id).first_or_404()
        item.title = (request.form.get('title') or '').strip() or None
        try:
            item.position = max(1, int(request.form.get('position') or item.position))
            raw_score = (request.form.get('min_score') or '').strip()
            item.min_score = float(raw_score) if raw_score else None
            if item.min_score is not None and not (0 <= item.min_score <= 100):
                raise ValueError
        except ValueError:
            flash('Posición o nota mínima no válida.', 'error')
            return redirect(url_for('admin_course_detail', course_id=course_id))
        item.required = bool(request.form.get('required'))
        item.require_pass = bool(request.form.get('require_pass'))
        db.session.commit()
        flash('Lección actualizada.', 'success')
        return redirect(url_for('admin_course_detail', course_id=course_id))

    @app.post('/admin/courses/<int:course_id>/items/<int:item_id>/delete')
    @admin_required
    def admin_course_delete_item(course_id, item_id):
        item = CourseItem.query.filter_by(id=item_id, course_id=course_id).first_or_404()
        if Attempt.query.filter_by(course_item_id=item.id).first():
            flash('No se puede eliminar una lección con intentos registrados. Puedes dejarla como no obligatoria.', 'error')
        else:
            db.session.delete(item)
            db.session.commit()
            flash('Lección retirada del curso.', 'success')
        return redirect(url_for('admin_course_detail', course_id=course_id))

    @app.post('/admin/courses/<int:course_id>/enroll')
    @admin_required
    def admin_course_enroll(course_id):
        course = db.get_or_404(Course, course_id)
        students = User.query.filter_by(role='student', active=True, archived=False).all()
        selected_ids = {int(x) for x in request.form.getlist('student_ids') if x.isdigit()}
        group_name = (request.form.get('group_name') or '').strip()
        if group_name:
            selected_ids.update(s.id for s in students if s.group_name == group_name)
        selected = [s for s in students if s.id in selected_ids]
        if not selected:
            flash('Selecciona alumnado o un grupo.', 'error')
            return redirect(url_for('admin_course_detail', course_id=course.id))
        created = 0
        for student in selected:
            enrollment = CourseEnrollment.query.filter_by(course_id=course.id, student_id=student.id).first()
            if enrollment:
                enrollment.active = True
            else:
                db.session.add(CourseEnrollment(course_id=course.id, student_id=student.id, active=True))
                created += 1
        db.session.commit()
        flash(f'Matrícula actualizada para {len(selected)} alumnos ({created} nuevas).', 'success')
        return redirect(url_for('admin_course_detail', course_id=course.id))

    @app.post('/admin/courses/<int:course_id>/unenroll/<int:student_id>')
    @admin_required
    def admin_course_unenroll(course_id, student_id):
        enrollment = CourseEnrollment.query.filter_by(course_id=course_id, student_id=student_id).first_or_404()
        enrollment.active = False
        db.session.commit()
        flash('Alumno retirado del curso; sus intentos se conservan.', 'success')
        return redirect(url_for('admin_course_detail', course_id=course_id))

    # ------------------------------------------------------------------
    # Biblioteca / reproductor SCORM común a ambos modos
    # ------------------------------------------------------------------
    @app.get('/library')
    @login_required
    def library():
        return render_template('library.html', packages=Package.query.order_by(Package.created_at.desc()).all())

    @app.route('/packages/upload', methods=['GET', 'POST'])
    @admin_required
    def upload_package():
        user = current_user()
        if request.method == 'GET':
            return render_template('upload.html', packages=Package.query.order_by(Package.title).all())
        uploaded = request.files.get('scorm_zip')
        if not uploaded or not uploaded.filename.lower().endswith('.zip'):
            flash('Debes seleccionar un archivo ZIP SCORM.', 'error')
            return redirect(request.url)
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            uploaded.save(tmp.name)
            tmp_path = Path(tmp.name)
        try:
            folder, info = import_scorm_zip(tmp_path, app.config['UPLOAD_ROOT'])
            package = Package(
                title=(request.form.get('title') or info.title).strip(),
                scorm_version=info.version,
                entrypoint=info.entrypoint,
                folder_name=folder,
                manifest_json=json.dumps(info.metadata, ensure_ascii=False),
                pass_score=float(request.form.get('pass_score') or 70),
                max_points=int(request.form.get('max_points') or 100),
                max_attempts=int(request.form.get('max_attempts') or 0),
                fullscreen=bool(request.form.get('fullscreen')),
                focus_limit=int(request.form.get('focus_limit') or 0),
                prerequisite_id=int(request.form['prerequisite_id']) if request.form.get('prerequisite_id') else None,
                created_by=user.id,
            )
            db.session.add(package)
            db.session.commit()
            flash('Paquete SCORM importado correctamente.', 'success')
            return redirect(url_for('package_detail', package_id=package.id))
        except Exception as exc:
            flash(f'No se pudo importar el SCORM: {exc}', 'error')
            return redirect(request.url)
        finally:
            tmp_path.unlink(missing_ok=True)

    @app.get('/packages/<int:package_id>')
    @login_required
    def package_detail(package_id):
        package = db.get_or_404(Package, package_id)
        attempts = Attempt.query.filter_by(package_id=package.id).order_by(Attempt.started_at.desc()).limit(50).all()
        return render_template('package_detail.html', package=package, attempts=attempts)

    @app.get('/packages/<int:package_id>/launch')
    @login_required
    def launch(package_id):
        package = db.get_or_404(Package, package_id)
        user = current_user()
        unlocked, reason = package_unlocked(package, user)
        if not unlocked:
            abort(403, description=reason)
        attempt = get_or_create_attempt(package, user)
        return redirect(url_for('player', attempt_id=attempt.id))

    @app.get('/player/<int:attempt_id>')
    @login_required
    def player(attempt_id):
        attempt = db.get_or_404(Attempt, attempt_id)
        user = current_user()
        if attempt.user_id != user.id and user.role != 'teacher':
            abort(403)
        assignment = attempt.assignment
        fullscreen = assignment_effective_fullscreen(assignment) if assignment else attempt.package.fullscreen
        focus_limit = assignment_effective_focus_limit(assignment) if assignment else attempt.package.focus_limit
        mode = assignment.mode if assignment else 'activity'
        if user.role == 'student' and attempt.course_item_id and attempt.course_item:
            exit_url = url_for('student_course', course_id=attempt.course_item.course_id)
        else:
            exit_url = url_for('student_dashboard') if user.role == 'student' else url_for('package_detail', package_id=attempt.package_id)
        return render_template(
            'player.html', attempt=attempt, package=attempt.package, assignment=assignment,
            fullscreen=fullscreen, focus_limit=focus_limit, mode=mode, exit_url=exit_url,
        )

    @app.get('/content/<int:package_id>/<path:filename>')
    @login_required
    def scorm_content(package_id, filename):
        package = db.get_or_404(Package, package_id)
        root = (app.config['UPLOAD_ROOT'] / package.folder_name).resolve()
        return send_from_directory(root, filename)

    @app.get('/api/attempts/<int:attempt_id>/state')
    @login_required
    def get_state(attempt_id):
        attempt = db.get_or_404(Attempt, attempt_id)
        user = current_user()
        if attempt.user_id != user.id and user.role != 'teacher':
            abort(403)
        return jsonify({
            'state': attempt.state(), 'status': attempt.status, 'score': attempt.score,
            'progress': attempt.progress, 'focus_losses': attempt.focus_losses,
        })

    @app.post('/api/attempts/<int:attempt_id>/state')
    @login_required
    def save_state(attempt_id):
        attempt = db.get_or_404(Attempt, attempt_id)
        if attempt.user_id != current_user().id:
            abort(403)
        data = request.get_json(force=True, silent=False) or {}
        state = data.get('state') or {}
        attempt.state_json = json.dumps(state, ensure_ascii=False)

        raw_score = state.get('cmi.core.score.raw', state.get('cmi.score.raw'))
        if raw_score not in (None, ''):
            try:
                attempt.score = float(raw_score)
            except (TypeError, ValueError):
                pass
        progress = state.get('cmi.progress_measure')
        if progress not in (None, ''):
            try:
                p = float(progress)
                attempt.progress = max(0, min(100, p * 100 if p <= 1 else p))
            except (TypeError, ValueError):
                pass
        lesson_status = state.get('cmi.core.lesson_status') or state.get('cmi.completion_status') or attempt.status
        success_status = state.get('cmi.success_status')
        finished = bool(data.get('finished'))
        if success_status == 'passed' or lesson_status == 'passed':
            attempt.status = 'passed'
        elif success_status == 'failed' or lesson_status == 'failed':
            attempt.status = 'failed'
        elif lesson_status in ('completed', 'complete'):
            attempt.status = 'completed'
        else:
            attempt.status = str(lesson_status or 'incomplete')
        if finished:
            attempt.finished_at = now_utc()
            if attempt.status in ('not attempted', 'unknown', 'incomplete'):
                attempt.status = 'completed'
        db.session.commit()

        grade_sync = {'attempted': False, 'ok': False, 'error': None}
        if finished and attempt.attachment and attempt.submission_id and attempt.attachment.classroom_attachment_id:
            grade_sync['attempted'] = True
            try:
                pct = attempt.score if attempt.score is not None else 0.0
                points = max(0.0, min(float(attempt.attachment.max_points), pct / 100.0 * attempt.attachment.max_points))
                pass_grade(
                    attempt.attachment.teacher,
                    course_id=attempt.attachment.course_id,
                    item_id=attempt.attachment.item_id,
                    attachment_id=attempt.attachment.classroom_attachment_id,
                    submission_id=attempt.submission_id,
                    points_earned=points,
                )
                grade_sync['ok'] = True
            except Exception as exc:
                grade_sync['error'] = str(exc)
        return jsonify({'ok': True, 'status': attempt.status, 'score': attempt.score, 'grade_sync': grade_sync})

    @app.post('/api/attempts/<int:attempt_id>/event')
    @login_required
    def attempt_event(attempt_id):
        attempt = db.get_or_404(Attempt, attempt_id)
        if attempt.user_id != current_user().id:
            abort(403)
        data = request.get_json(force=True, silent=True) or {}
        event_type = str(data.get('type') or 'event')[:64]
        if event_type in ('blur', 'hidden', 'focus-loss'):
            attempt.focus_losses += 1
        event = Event(
            attempt_id=attempt.id, event_type=event_type,
            payload_json=json.dumps(data.get('payload') or {}, ensure_ascii=False),
        )
        db.session.add(event)
        db.session.commit()
        limit = assignment_effective_focus_limit(attempt.assignment) if attempt.assignment else attempt.package.focus_limit
        should_finish = bool(limit and attempt.focus_losses >= limit)
        return jsonify({'ok': True, 'focus_losses': attempt.focus_losses, 'should_finish': should_finish})

    # ------------------------------------------------------------------
    # Google Classroom Add-on: permanece disponible, pero es opcional
    # ------------------------------------------------------------------
    @app.get('/addon-discovery')
    def addon_discovery():
        for key in ('courseId', 'itemId', 'itemType', 'addOnToken', 'login_hint'):
            if request.args.get(key):
                session[f'addon_{key}'] = request.args.get(key)
        if not current_user():
            session['return_to'] = request.url
            return render_template('addon_login.html', login_hint=request.args.get('login_hint'))
        packages = Package.query.order_by(Package.title).all()
        return render_template('discovery.html', packages=packages)

    @app.post('/addon-discovery/attach/<int:package_id>')
    @login_required
    def attach_package(package_id):
        user = current_user()
        user.role = 'teacher'
        db.session.commit()
        package = db.get_or_404(Package, package_id)
        course_id = session.get('addon_courseId')
        item_id = session.get('addon_itemId')
        item_type = session.get('addon_itemType') or 'courseWork'
        token = session.get('addon_addOnToken')
        if not all([course_id, item_id, token]):
            abort(400, description='Faltan parámetros de contexto de Classroom.')
        urls = {
            'teacher': f"{app.config['BASE_URL']}/classroom/teacher",
            'student': f"{app.config['BASE_URL']}/classroom/student",
            'grader': f"{app.config['BASE_URL']}/classroom/grader",
        }
        resp = create_attachment(
            user, course_id=course_id, item_id=item_id, item_type=item_type,
            add_on_token=token, package=package, urls=urls,
        )
        attachment = Attachment(
            classroom_attachment_id=resp.get('id'), package_id=package.id,
            course_id=course_id, item_id=item_id, item_type=item_type,
            teacher_user_id=user.id, max_points=int(resp.get('maxPoints') or package.max_points),
        )
        db.session.add(attachment)
        db.session.commit()
        return render_template('attached.html', package=package, attachment=attachment)

    def classroom_attachment_from_query():
        aid = request.args.get('attachmentId')
        attachment = Attachment.query.filter_by(classroom_attachment_id=aid).first() if aid else None
        if not attachment:
            abort(404, description='No se encontró el adjunto de Classroom.')
        return attachment

    @app.get('/classroom/student')
    @login_required
    def classroom_student():
        user = current_user()
        attachment = classroom_attachment_from_query()
        submission_id = request.args.get('submissionId')
        if not submission_id and app.config['CLASSROOM_ENABLED']:
            try:
                context = get_addon_context(
                    user, course_id=attachment.course_id,
                    item_id=attachment.item_id, item_type=attachment.item_type,
                )
                submission_id = (context.get('studentContext') or {}).get('submissionId')
            except Exception as exc:
                flash(f'No se pudo validar el contexto de Classroom: {exc}', 'error')
        unlocked, reason = package_unlocked(attachment.package, user)
        if not unlocked:
            abort(403, description=reason)
        attempt = get_or_create_attempt(attachment.package, user, attachment, submission_id)
        return redirect(url_for('player', attempt_id=attempt.id))

    @app.get('/classroom/teacher')
    @login_required
    def classroom_teacher():
        attachment = classroom_attachment_from_query()
        attempts = Attempt.query.filter_by(attachment_id=attachment.id).order_by(Attempt.updated_at.desc()).all()
        return render_template('teacher.html', attachment=attachment, attempts=attempts)

    @app.get('/classroom/grader')
    @login_required
    def classroom_grader():
        attachment = classroom_attachment_from_query()
        submission_id = request.args.get('submissionId')
        attempt = Attempt.query.filter_by(attachment_id=attachment.id, submission_id=submission_id).order_by(Attempt.id.desc()).first()
        return render_template('grader.html', attachment=attachment, attempt=attempt)

    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(400)
    @app.errorhandler(503)
    def error_page(err):
        return render_template(
            'error.html', code=getattr(err, 'code', 500),
            message=getattr(err, 'description', str(err)),
        ), getattr(err, 'code', 500)

    return app


app = create_app()


if __name__ == '__main__':
    if os.getenv('OAUTHLIB_INSECURE_TRANSPORT') is None and app.config['BASE_URL'].startswith('http://localhost'):
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=os.getenv('FLASK_DEBUG', '0') == '1')
