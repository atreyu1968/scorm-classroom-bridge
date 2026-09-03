#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${SCORM_REPO_URL:-https://github.com/atreyu1968/scorm-classroom-bridge.git}"
INSTALL_DIR="${SCORM_INSTALL_DIR:-/opt/scorm-classroom-bridge}"
DOMAIN="${SCORM_DOMAIN:-}"
ADMIN_USERNAME="${SCORM_ADMIN_USERNAME:-profesor}"
ADMIN_PASSWORD="${SCORM_ADMIN_PASSWORD:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --admin-user) ADMIN_USERNAME="${2:-}"; shift 2 ;;
    --admin-password) ADMIN_PASSWORD="${2:-}"; shift 2 ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
done

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Ejecuta este instalador con sudo/root." >&2
  exit 1
fi

log(){ printf '\n\033[1;34m[SCORM Bridge]\033[0m %s\n' "$*"; }
fail(){ printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

install_base_packages(){
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y ca-certificates curl git openssl
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y ca-certificates curl git openssl
  elif command -v yum >/dev/null 2>&1; then
    yum install -y ca-certificates curl git openssl
  else
    fail "Distribución no soportada automáticamente. Instala Docker, Git, curl y OpenSSL y vuelve a ejecutar."
  fi
}

install_docker(){
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return
  fi
  log "Instalando Docker Engine y Docker Compose…"
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh
  systemctl enable --now docker 2>/dev/null || true
  docker compose version >/dev/null 2>&1 || fail "Docker Compose no quedó disponible."
}

log "Preparando dependencias del sistema…"
install_base_packages
install_docker

log "Descargando/actualizando el proyecto…"
mkdir -p "$(dirname "$INSTALL_DIR")"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" fetch --all --prune
  git -C "$INSTALL_DIR" pull --ff-only
elif [[ -e "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null || true)" ]]; then
  fail "$INSTALL_DIR existe y no es un repositorio Git vacío."
else
  rm -rf "$INSTALL_DIR"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"
mkdir -p instance uploads/scorm backups

if [[ -z "$ADMIN_PASSWORD" ]]; then
  ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '=+/\n' | cut -c1-20)"
fi
SECRET_KEY="$(openssl rand -hex 32)"
TOKEN_KEY="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"

if [[ -n "$DOMAIN" ]]; then
  DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%%/*}"
  BASE_URL="https://${DOMAIN}"
  SITE_ADDRESS="${DOMAIN}"
  COOKIE_SECURE="true"
else
  SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -n "$SERVER_IP" ]] || SERVER_IP="127.0.0.1"
  BASE_URL="http://${SERVER_IP}"
  SITE_ADDRESS="http://:80"
  COOKIE_SECURE="false"
fi

if [[ ! -f .env ]]; then
  log "Generando configuración segura…"
  cat > .env <<ENVEOF
SECRET_KEY=${SECRET_KEY}
BASE_URL=${BASE_URL}
DATABASE_URL=sqlite:////app/instance/scorm_classroom.db
MAX_UPLOAD_MB=300
UPLOAD_ROOT=/app/uploads/scorm
LOCAL_TIMEZONE=Atlantic/Canary
DEV_AUTH=false
ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
CLASSROOM_ENABLED=false
SESSION_COOKIE_SECURE=${COOKIE_SECURE}
SESSION_COOKIE_SAMESITE=Lax
SITE_ADDRESS=${SITE_ADDRESS}
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=${BASE_URL}/auth/google/callback
TOKEN_ENCRYPTION_KEY=${TOKEN_KEY}
ENVEOF
  chmod 600 .env
else
  log "Se conserva el archivo .env existente."
fi

log "Construyendo e iniciando los contenedores…"
docker compose up -d --build

log "Comprobando el servicio…"
for _ in $(seq 1 45); do
  if docker compose exec -T scorm-classroom python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3)" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
if ! docker compose ps --status running | grep -q scorm-classroom; then
  docker compose logs --tail=100
  fail "La aplicación no ha arrancado correctamente."
fi

cat <<OUT

============================================================
 SCORM Classroom Bridge instalado
============================================================
 URL:            ${BASE_URL}
 Panel docente:  ${BASE_URL}/admin
 Usuario:        ${ADMIN_USERNAME}
 Contraseña:     ${ADMIN_PASSWORD}
 Directorio:     ${INSTALL_DIR}

 Comandos útiles:
   cd ${INSTALL_DIR} && sudo bash upgrade.sh
   cd ${INSTALL_DIR} && sudo bash backup.sh
   cd ${INSTALL_DIR} && sudo docker compose logs -f
============================================================
OUT

if [[ -z "$DOMAIN" ]]; then
  echo "AVISO: el acceso está en HTTP. Para producción y alumnado configura un dominio y HTTPS."
else
  echo "Caddy solicitará automáticamente el certificado HTTPS cuando el DNS de ${DOMAIN} apunte a este servidor."
fi
