#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Ejecuta con sudo/root" >&2; exit 1; }
cd "$(dirname "$(readlink -f "$0")")"
docker compose down
if [[ "${1:-}" == "--purge-data" ]]; then
  echo "Se eliminarán base de datos, SCORM subidos y configuración."
  rm -rf instance uploads .env backups
  docker volume prune -f >/dev/null 2>&1 || true
  echo "Datos eliminados."
else
  echo "Contenedores detenidos. Los datos se conservan. Usa --purge-data para borrarlos."
fi
