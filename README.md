# SCORM Classroom Bridge — LMS Link Mode

Plataforma ligera para publicar, asignar y secuenciar paquetes **SCORM 1.2 / SCORM 2004** sin obligar al alumnado a iniciar sesión con Google. Está pensada para centros educativos en los que las cuentas institucionales bloquean aplicaciones externas, manteniendo Google Classroom como integración opcional.

## Instalación en un comando

Con dominio y HTTPS automático:

```bash
curl -fsSL https://raw.githubusercontent.com/atreyu1968/scorm-classroom-bridge/main/install.sh | sudo bash -s -- --domain scorm.ejemplo.es
```

Sin dominio, para una prueba provisional por IP:

```bash
curl -fsSL https://raw.githubusercontent.com/atreyu1968/scorm-classroom-bridge/main/install.sh | sudo bash
```

El instalador:

- instala Git, Docker Engine y Docker Compose si hacen falta;
- clona/actualiza el repositorio en `/opt/scorm-classroom-bridge`;
- genera secretos y contraseña de administración cuando no se proporcionan;
- crea `.env` con permisos restringidos;
- construye la aplicación;
- inicia Flask/Gunicorn y Caddy;
- configura HTTPS automáticamente cuando se proporciona un dominio;
- conserva base de datos y SCORM en volúmenes/directorios persistentes.

Consulta [`docs/INSTALLATION.md`](docs/INSTALLATION.md) para instalación, actualización, copias y desinstalación.

## Funciones principales

### Acceso del alumnado sin Google

- Código personal + PIN opcional.
- Enlace personal permanente `/u/<token>`.
- Enlace individual de actividad `/a/<token>`.
- Enlace individual de examen `/e/<token>`.
- Tokens no predecibles y PIN almacenado mediante hash.
- Vinculación opcional al primer dispositivo.

### Gestión completa del alumnado

Desde `/admin/students`:

- alta manual;
- importación CSV;
- edición de nombre, grupo, correo, código y PIN;
- cambio de grupo individual o masivo;
- activación/desactivación;
- archivado/baja conservando todo el historial;
- restauración;
- regeneración del enlace personal;
- eliminación definitiva protegida mediante confirmación;
- operaciones masivas sobre alumnado seleccionado.

### Cursos de varias lecciones SCORM

Además de asignar SCORM independientes, el profesor puede crear **cursos/itinerarios**:

```text
Curso
├── Lección 1 → SCORM
├── Lección 2 → SCORM
├── Lección 3 → SCORM
└── Lección 4 → SCORM
```

Cada curso puede ser:

- **secuencial**, bloqueando las lecciones posteriores;
- **libre**, permitiendo cualquier orden.

Por lección se puede definir:

- obligatoriedad;
- exigencia de superar la anterior;
- nota mínima;
- posición/orden.

El alumnado ve su progreso de curso desde su mismo enlace personal.

### Asignaciones individuales

- por alumno o grupo;
- actividad o examen;
- fecha/hora de apertura y cierre;
- número de intentos;
- PIN obligatorio opcional;
- bloqueo de dispositivo;
- pantalla completa en examen;
- detección y registro de pérdidas de foco;
- restablecimiento de dispositivo por el profesor.

### Runtime SCORM

- importación segura de ZIP con `imsmanifest.xml`;
- SCORM 1.2 y SCORM 2004 runtime;
- persistencia CMI;
- `suspend_data`;
- reanudación;
- progreso;
- puntuación;
- completion/success;
- intentos e incidencias.

> No implementa la totalidad de SCORM 2004 Sequencing & Navigation para paquetes multi-SCO especialmente complejos. El secuenciado de cursos de esta aplicación opera a nivel de paquete/lección.

## URLs

```text
/                         portada
/admin                    panel del profesorado
/admin/students           alumnado
/admin/courses            cursos e itinerarios
/admin/assignments        SCORM individuales
/admin/results            resultados
/student/access           acceso por código/PIN
/student                  aula del alumno
/u/<token>                enlace personal
/a/<token>                actividad
/e/<token>                examen
/health                    estado del servicio
```

## Primer uso

1. Instala la aplicación.
2. Entra en `https://tu-dominio/admin`.
3. Sube tus ZIP SCORM.
4. Importa/crea el alumnado.
5. Crea un curso con varias lecciones o una asignación individual.
6. Matricula/asigna al alumnado.
7. Entrega a cada alumno su enlace personal una sola vez.

Las actividades y cursos nuevos aparecerán automáticamente en su aula.

## Actualización

```bash
cd /opt/scorm-classroom-bridge
sudo bash upgrade.sh
```

El script crea una copia de seguridad antes de actualizar.

## Copias de seguridad

```bash
cd /opt/scorm-classroom-bridge
sudo bash backup.sh
```

Se incluyen `instance`, `uploads` y `.env`.

## Configuración manual

Si no utilizas el instalador:

```bash
git clone https://github.com/atreyu1968/scorm-classroom-bridge.git
cd scorm-classroom-bridge
cp .env.example .env
nano .env
docker compose up -d --build
```

Los valores esenciales son:

```dotenv
BASE_URL=https://scorm.ejemplo.es
SITE_ADDRESS=scorm.ejemplo.es
ADMIN_USERNAME=profesor
ADMIN_PASSWORD=una-clave-segura
CLASSROOM_ENABLED=false
LOCAL_TIMEZONE=Atlantic/Canary
```

## Google Classroom opcional

El modo por enlace **no necesita Google OAuth**. Si el administrador del dominio educativo permite posteriormente la integración, se conserva el Add-on/OAuth mediante:

```dotenv
CLASSROOM_ENABLED=true
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
TOKEN_ENCRYPTION_KEY=...
SESSION_COOKIE_SAMESITE=None
```

Consulta [`docs/GOOGLE_CLASSROOM_SETUP.md`](docs/GOOGLE_CLASSROOM_SETUP.md).

## Datos y seguridad

- No subas `.env`, bases SQLite ni copias de seguridad a GitHub.
- En producción utiliza HTTPS.
- El enlace personal del alumno funciona como credencial de capacidad; no publiques listados completos de enlaces.
- Para evaluaciones, utiliza PIN y bloqueo de dispositivo cuando proceda.
- Archivar un alumno conserva su historial; la eliminación definitiva lo borra.
- Revisa las obligaciones de protección de datos aplicables a tu centro.

Consulta [`SECURITY.md`](SECURITY.md).

## Desarrollo y validación

```bash
python -m pytest -q
python -m py_compile app.py models.py config.py security.py scorm_manifest.py classroom_api.py
docker build -t scorm-classroom-bridge .
```

GitHub Actions ejecuta estas comprobaciones automáticamente en cada `push` y `pull_request`.

## Estado

Versión: **3.0.0-lms**.

Repositorio público previsto: `atreyu1968/scorm-classroom-bridge`.

No se incluye una licencia de software abierta por defecto; la publicación pública del repositorio no implica por sí sola cesión de derechos de reutilización.
