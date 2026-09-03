#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Ejecuta con sudo/root" >&2; exit 1; }
cd "$(dirname "$(readlink -f "$0")")"
echo "[SCORM Bridge] Creando copia de seguridad previa…"
bash backup.sh --quiet
echo "[SCORM Bridge] Actualizando desde GitHub…"
git fetch --all --prune
git pull --ff-only
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null 2>&1 || true
echo "[SCORM Bridge] Actualización completada."
