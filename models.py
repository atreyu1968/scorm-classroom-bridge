from datetime import datetime, timezone
import json
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_sub = db.Column(db.String(255), unique=True, nullable=True, index=True)
    email = db.Column(db.String(320), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), default='student', nullable=False)
    refresh_token_enc = db.Column(db.Text, nullable=True)

    # Credenciales locales. El alumnado no necesita Google.
    username = db.Column(db.String(128), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    pin_hash = db.Column(db.String(255), nullable=True)
    student_code = db.Column(db.String(64), unique=True, nullable=True, index=True)
    access_token = db.Column(db.String(128), unique=True, nullable=True, index=True)
    group_name = db.Column(db.String(128), nullable=True, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Package(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    scorm_version = db.Column(db.String(32), default='1.2', nullable=False)
    entrypoint = db.Column(db.Text, nullable=False)
    folder_name = db.Column(db.String(255), unique=True, nullable=False)
    manifest_json = db.Column(db.Text, default='{}', nullable=False)
    pass_score = db.Column(db.Float, default=70.0, nullable=False)
    max_points = db.Column(db.Integer, default=100, nullable=False)
    max_attempts = db.Column(db.Integer, default=0, nullable=False)  # 0 = ilimitados
    fullscreen = db.Column(db.Boolean, default=False, nullable=False)
    focus_limit = db.Column(db.Integer, default=0, nullable=False)  # 0 = solo registrar
    prerequisite_id = db.Column(db.Integer, db.ForeignKey('package.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    prerequisite = db.relationship('Package', remote_side=[id], uselist=False)

    def manifest(self):
        try:
            return json.loads(self.manifest_json or '{}')
        except json.JSONDecodeError:
            return {}


class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    classroom_attachment_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    package_id = db.Column(db.Integer, db.ForeignKey('package.id'), nullable=False)
    course_id = db.Column(db.String(255), nullable=True, index=True)
    item_id = db.Column(db.String(255), nullable=True, index=True)
    item_type = db.Column(db.String(64), default='courseWork', nullable=False)
    teacher_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    max_points = db.Column(db.Integer, default=100, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    package = db.relationship('Package')
    teacher = db.relationship('User')


class Assignment(db.Model):
    """Asignación autónoma por enlace, independiente de Google Classroom."""
    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(db.Integer, db.ForeignKey('package.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    token = db.Column(db.String(128), unique=True, nullable=False, index=True)
    mode = db.Column(db.String(16), default='activity', nullable=False)  # activity | exam
    available_from = db.Column(db.DateTime(timezone=True), nullable=True)
    deadline = db.Column(db.DateTime(timezone=True), nullable=True)
    max_attempts = db.Column(db.Integer, nullable=True)  # NULL = hereda del paquete; 0 = ilimitados
    require_pin = db.Column(db.Boolean, default=False, nullable=False)
    device_lock = db.Column(db.Boolean, default=False, nullable=False)
    device_hash = db.Column(db.String(128), nullable=True)
    fullscreen = db.Column(db.Boolean, nullable=True)  # NULL = hereda del paquete
    focus_limit = db.Column(db.Integer, nullable=True)  # NULL = hereda del paquete
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    package = db.relationship('Package')
    student = db.relationship('User', foreign_keys=[student_id])
    creator = db.relationship('User', foreign_keys=[created_by])


class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(db.Integer, db.ForeignKey('package.id'), nullable=False, index=True)
    attachment_id = db.Column(db.Integer, db.ForeignKey('attachment.id'), nullable=True, index=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=True, index=True)
    course_item_id = db.Column(db.Integer, db.ForeignKey('course_item.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    submission_id = db.Column(db.String(255), nullable=True, index=True)
    status = db.Column(db.String(64), default='incomplete', nullable=False)
    score = db.Column(db.Float, nullable=True)
    progress = db.Column(db.Float, default=0.0, nullable=False)
    state_json = db.Column(db.Text, default='{}', nullable=False)
    focus_losses = db.Column(db.Integer, default=0, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)

    package = db.relationship('Package')
    attachment = db.relationship('Attachment')
    assignment = db.relationship('Assignment')
    course_item = db.relationship('CourseItem')
    user = db.relationship('User')

    def state(self):
        try:
            return json.loads(self.state_json or '{}')
        except json.JSONDecodeError:
            return {}


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('attempt.id'), nullable=False, index=True)
    event_type = db.Column(db.String(64), nullable=False)
    payload_json = db.Column(db.Text, default='{}', nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    attempt = db.relationship('Attempt')


class Course(db.Model):
    """Curso/itinerario compuesto por varias lecciones SCORM consecutivas."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    sequential = db.Column(db.Boolean, default=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    creator = db.relationship('User', foreign_keys=[created_by])
    items = db.relationship('CourseItem', back_populates='course', cascade='all, delete-orphan', order_by='CourseItem.position')
    enrollments = db.relationship('CourseEnrollment', back_populates='course', cascade='all, delete-orphan')


class CourseItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False, index=True)
    package_id = db.Column(db.Integer, db.ForeignKey('package.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=True)
    position = db.Column(db.Integer, default=1, nullable=False)
    required = db.Column(db.Boolean, default=True, nullable=False)
    require_pass = db.Column(db.Boolean, default=True, nullable=False)
    min_score = db.Column(db.Float, nullable=True)

    course = db.relationship('Course', back_populates='items')
    package = db.relationship('Package')


class CourseEnrollment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    enrolled_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    course = db.relationship('Course', back_populates='enrollments')
    student = db.relationship('User')

    __table_args__ = (db.UniqueConstraint('course_id', 'student_id', name='uq_course_student'),)
