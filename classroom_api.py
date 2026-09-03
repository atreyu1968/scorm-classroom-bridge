from __future__ import annotations
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from flask import current_app
from security import decrypt_text

TEACHER_SCOPE = 'https://www.googleapis.com/auth/classroom.addons.teacher'
STUDENT_SCOPE = 'https://www.googleapis.com/auth/classroom.addons.student'


def credentials_from_user(user):
    refresh_token = decrypt_text(user.refresh_token_enc, current_app.config['TOKEN_ENCRYPTION_KEY'])
    if not refresh_token:
        raise RuntimeError('El docente no dispone de token OAuth offline para sincronizar calificaciones.')
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=current_app.config['GOOGLE_CLIENT_ID'],
        client_secret=current_app.config['GOOGLE_CLIENT_SECRET'],
        scopes=['openid', 'email', 'profile', TEACHER_SCOPE, STUDENT_SCOPE],
    )


def service_for_user(user):
    return build('classroom', 'v1', credentials=credentials_from_user(user), cache_discovery=False)


def parent_resource(service, item_type: str):
    courses = service.courses()
    if item_type in ('announcement', 'announcements'):
        return courses.announcements()
    if item_type in ('courseWorkMaterial', 'courseWorkMaterials'):
        return courses.courseWorkMaterials()
    return courses.courseWork()


def create_attachment(user, *, course_id, item_id, item_type, add_on_token, package, urls):
    service = service_for_user(user)
    body = {
        'title': package.title,
        'teacherViewUri': {'uri': urls['teacher']},
        'studentViewUri': {'uri': urls['student']},
        'studentWorkReviewUri': {'uri': urls['grader']},
        'maxPoints': int(package.max_points),
    }
    return parent_resource(service, item_type).addOnAttachments().create(
        courseId=course_id,
        itemId=item_id,
        addOnToken=add_on_token,
        body=body,
    ).execute()


def get_addon_context(user, *, course_id, item_id, item_type):
    service = service_for_user(user)
    return parent_resource(service, item_type).getAddOnContext(
        courseId=course_id,
        itemId=item_id,
    ).execute()


def pass_grade(teacher, *, course_id, item_id, attachment_id, submission_id, points_earned):
    service = service_for_user(teacher)
    return service.courses().courseWork().addOnAttachments().studentSubmissions().patch(
        courseId=course_id,
        itemId=item_id,
        attachmentId=attachment_id,
        submissionId=submission_id,
        updateMask='pointsEarned',
        body={'pointsEarned': float(points_earned)},
    ).execute()
