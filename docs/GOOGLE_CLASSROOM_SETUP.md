# Registro como complemento de Google Classroom

## 1. Requisitos

- Google Workspace for Education Plus o Teaching and Learning Upgrade para usar complementos de Classroom.
- Un proyecto de Google Cloud.
- Dominio HTTPS público para esta aplicación.
- Google Classroom API habilitada.
- Google Workspace Marketplace SDK habilitado.

## 2. OAuth

Crea un cliente OAuth 2.0 de tipo **Aplicación web**.

URI de redirección autorizada:

`https://TU_DOMINIO/auth/google/callback`

Scopes necesarios:

- `openid`
- `email`
- `profile`
- `https://www.googleapis.com/auth/classroom.addons.teacher`
- `https://www.googleapis.com/auth/classroom.addons.student`

La aplicación solicita acceso offline para el docente porque la devolución de calificaciones puede producirse cuando finaliza el SCORM.

## 3. Marketplace SDK

En **App Integration > Classroom add-on**, configura:

- Attachment Setup URI / Discovery URI: `https://TU_DOMINIO/addon-discovery`

Las URI que el propio complemento registra al adjuntar una actividad son:

- Teacher View: `https://TU_DOMINIO/classroom/teacher`
- Student View: `https://TU_DOMINIO/classroom/student`
- Student Work Review: `https://TU_DOMINIO/classroom/grader`

`studentWorkReviewUri` y un `maxPoints` positivo convierten el adjunto en una actividad compatible con devolución de calificaciones.

## 4. Instalación de pruebas

1. Añade las cuentas de profesor y alumno como usuarios de prueba de OAuth.
2. Configura Marketplace como aplicación privada del dominio o como borrador de prueba según tu escenario.
3. Instala/autoriza el complemento con el administrador de Workspace.
4. En Classroom web crea una tarea, abre **Complementos** y elige SCORM Classroom Bridge.
5. Selecciona un paquete de la biblioteca y pulsa **Adjuntar**.
6. Abre la tarea como alumno y completa el paquete.
7. Comprueba la vista del profesor y la calificación preliminar.

## 5. Producción

Antes de un despliegue real:

- `DEV_AUTH=false`
- HTTPS obligatorio.
- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_SAMESITE=None` para el uso embebido en iframe, tras validar la estrategia vigente de cookies/Storage Access de Google.
- `TOKEN_ENCRYPTION_KEY` configurada.
- Sustituir SQLite por PostgreSQL si habrá varios centros o carga concurrente alta.
- Almacenar paquetes en almacenamiento de objetos si se ejecutan varias réplicas del servicio.
- Añadir política de privacidad, condiciones de servicio y proceso de borrado/exportación de datos.
