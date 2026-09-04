# SCORM Classroom Bridge — LMS Link Mode

Plataforma ligera para publicar, asignar y secuenciar paquetes **SCORM 1.2 / SCORM 2004** sin obligar al alumnado a iniciar sesión con Google. Está pensada para centros educativos en los que las cuentas institucionales bloquean aplicaciones externas, manteniendo Google Classroom como integración opcional.

## Instalación recomendada en Ubuntu desde cero

Estas instrucciones están pensadas también para un servidor Ubuntu que **no esté actualizado y no tenga instalados Git, curl ni Docker**.

### 1. Acceder al servidor

Conéctate por SSH con un usuario que tenga permisos `sudo`:

```bash
ssh usuario@IP_DEL_SERVIDOR
```

Comprueba la versión de Ubuntu:

```bash
cat /etc/os-release
```

Se recomienda utilizar una versión LTS de Ubuntu actualmente soportada.

### 2. Actualizar completamente Ubuntu

Primero actualiza el índice de paquetes y el sistema:

```bash
sudo apt update
sudo DEBIAN_FRONTEND=noninteractive apt full-upgrade -y
sudo apt autoremove -y
sudo apt autoclean
```

Si Ubuntu indica que es necesario reiniciar, o existe el archivo `/var/run/reboot-required`, reinicia antes de continuar:

```bash
if [ -f /var/run/reboot-required ]; then sudo reboot; fi
```

Tras el reinicio, vuelve a conectarte por SSH.

### 3. Instalar las utilidades mínimas necesarias

El comando de autoinstalación se descarga con `curl`, por lo que en un servidor completamente limpio hay que instalar primero las herramientas básicas:

```bash
sudo apt update
sudo apt install -y \
  ca-certificates \
  curl \
  git \
  openssl \
  unzip
```

Comprueba que están disponibles:

```bash
curl --version
git --version
openssl version
```

> **No es necesario instalar Docker manualmente.** `install.sh` comprueba si Docker Engine y Docker Compose están disponibles y, si faltan, los instala automáticamente.

### 4. Preparar red, dominio y cortafuegos

Para utilizar HTTPS automático con Caddy, el dominio debe apuntar mediante DNS a la IP pública del servidor y los puertos **80/TCP y 443/TCP** deben ser accesibles desde Internet.

Si utilizas UFW, conserva primero el acceso SSH y abre HTTP/HTTPS:

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

Si UFW ya estaba configurado, revisa sus reglas antes de modificarlo. Si el servidor está detrás de un router, NAT, firewall externo o proveedor cloud, abre/redirige también allí los puertos 80 y 443.

Antes de instalar con dominio, comprueba que el DNS resuelve correctamente:

```bash
getent hosts scorm.ejemplo.es
```

Debe devolver la IP correspondiente al servidor.

### 5. Ejecutar el autoinstalador

#### Con dominio y HTTPS automático — recomendado

Sustituye `scorm.ejemplo.es` por tu dominio real:

```bash
curl -fsSL https://raw.githubusercontent.com/atreyu1968/scorm-classroom-bridge/main/install.sh | sudo bash -s -- --domain scorm.ejemplo.es
```

El instalador:

- instala las dependencias base que todavía falten;
- instala Docker Engine y Docker Compose si no existen;
- habilita e inicia Docker;
- clona/actualiza este repositorio en `/opt/scorm-classroom-bridge`;
- crea los directorios persistentes necesarios;
- genera automáticamente `SECRET_KEY` y claves internas;
- genera una contraseña de administración segura cuando no se proporciona una;
- crea `.env` con permisos restringidos;
- construye la imagen Docker de la aplicación;
- inicia Flask/Gunicorn y Caddy mediante Docker Compose;
- configura HTTPS automáticamente cuando se proporciona un dominio;
- conserva base de datos y paquetes SCORM en almacenamiento persistente.

#### Sin dominio — prueba provisional por IP

```bash
curl -fsSL https://raw.githubusercontent.com/atreyu1968/scorm-classroom-bridge/main/install.sh | sudo bash
```

Este modo es apropiado para comprobar la instalación antes de configurar DNS/HTTPS.

### 6. Verificar la instalación

Comprueba Docker y los contenedores:

```bash
docker --version
docker compose version
cd /opt/scorm-classroom-bridge
sudo docker compose ps
```

Comprueba los últimos registros si fuera necesario:

```bash
cd /opt/scorm-classroom-bridge
sudo docker compose logs --tail=100
```

Con dominio, comprueba el endpoint de salud:

```bash
curl -fsS https://scorm.ejemplo.es/health
```

Después entra en:

```text
https://scorm.ejemplo.es/admin
```

Las credenciales iniciales se muestran al finalizar `install.sh`. Guárdalas en un lugar seguro.

### Instalación resumida para un Ubuntu ya preparado

Si Ubuntu ya está actualizado y dispone de `curl`, puedes ir directamente al instalador:

```bash
curl -fsSL https://raw.githubusercontent.com/atreyu1968/scorm-classroom-bridge/main/install.sh | sudo bash -s -- --domain scorm.ejemplo.es
```

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

## Actualización de la aplicación

```bash
cd /opt/scorm-classroom-bridge
sudo bash upgrade.sh
```

El script crea una copia de seguridad antes de actualizar.

Para mantener también Ubuntu actualizado periódicamente:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt autoremove -y
```

Si una actualización del sistema requiere reinicio:

```bash
if [ -f /var/run/reboot-required ]; then sudo reboot; fi
```

## Copias de seguridad

```bash
cd /opt/scorm-classroom-bridge
sudo bash backup.sh
```

Se incluyen `instance`, `uploads` y `.env`.

## Configuración manual

Si no utilizas el instalador, instala primero los requisitos:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git openssl unzip
```

Después:

```bash
git clone https://github.com/atreyu1968/scorm-classroom-bridge.git
cd scorm-classroom-bridge
cp .env.example .env
nano .env
```

Instala Docker Engine y Docker Compose antes de ejecutar manualmente el proyecto, o utiliza `install.sh` para que esa parte sea automática.

Con Docker disponible:

```bash
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

Repositorio público: `atreyu1968/scorm-classroom-bridge`.

No se incluye una licencia de software abierta por defecto; la publicación pública del repositorio no implica por sí sola cesión de derechos de reutilización.
