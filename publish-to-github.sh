#!/usr/bin/env bash
set -Eeuo pipefail
OWNER="${GITHUB_OWNER:-atreyu1968}"
REPO="${GITHUB_REPO:-scorm-classroom-bridge}"
VISIBILITY="${GITHUB_VISIBILITY:-public}"

command -v gh >/dev/null 2>&1 || { echo "Falta GitHub CLI (gh). Instálalo desde https://cli.github.com/" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Autentica GitHub CLI con: gh auth login" >&2; exit 1; }

cd "$(dirname "$(readlink -f "$0")")"
if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "El repositorio $OWNER/$REPO ya existe; se utilizará el existente."
else
  gh repo create "$OWNER/$REPO" --"$VISIBILITY" --description "LMS ligero SCORM 1.2/2004 con acceso por enlace, cursos secuenciales y Classroom opcional" --source=. --remote=origin
fi

git branch -M main
git push -u origin main
echo "Publicado: https://github.com/$OWNER/$REPO"
