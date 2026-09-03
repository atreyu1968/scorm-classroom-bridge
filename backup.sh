#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
mkdir -p backups
stamp="$(date +%Y%m%d_%H%M%S)"
out="backups/scorm_bridge_${stamp}.tar.gz"
tar -czf "$out" instance uploads .env
find backups -type f -name 'scorm_bridge_*.tar.gz' -mtime +30 -delete || true
[[ "${1:-}" == "--quiet" ]] || echo "Copia creada: $out"
