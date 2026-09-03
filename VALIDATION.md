# Validación de la versión 3.0.0-lms

Comprobaciones realizadas sobre el paquete preparado para GitHub:

- `python -m py_compile` sobre los módulos Python principales: correcto.
- Parseo sintáctico de todas las plantillas Jinja: correcto.
- Comprobación de referencias `url_for` de plantillas contra endpoints definidos: correcto.
- `bash -n` sobre `install.sh`, `upgrade.sh`, `backup.sh`, `uninstall.sh` y `publish-to-github.sh`: correcto.
- `pytest -q`: 1 prueba del parser de manifiestos SCORM superada.
- Archivos `.env`, SQLite, cachés, copias `.bak` y contenidos subidos excluidos de Git/Docker.

La construcción real de la imagen Docker se valida además mediante GitHub Actions (`.github/workflows/validate.yml`) cuando el repositorio recibe el primer `push`.
