# Arquitectura

```text
Google Classroom
   ├─ Attachment Discovery iframe ───────┐
   ├─ Student View iframe ───────────────┤
   ├─ Teacher View iframe ───────────────┤
   └─ Student Work Review iframe ────────┤
                                         ▼
                              SCORM Classroom Bridge
                              ├─ Google SSO / OAuth
                              ├─ Biblioteca SCORM
                              ├─ Importador imsmanifest.xml
                              ├─ Runtime SCORM 1.2
                              ├─ Runtime SCORM 2004
                              ├─ Seguimiento CMI
                              ├─ Reanudación / intentos
                              ├─ Prerrequisitos
                              ├─ Registro de foco
                              └─ Grade passback
                                         │
                                         ▼
                               Google Classroom API
```

## Runtime

El SCO se sirve desde el mismo origen y se carga en un `iframe` hijo. La página contenedora publica:

- `window.API` para SCORM 1.2.
- `window.API_1484_11` para SCORM 2004.

Cada `SetValue` se mantiene en memoria y se persiste con *debounce*. `Commit`, `Finish` o `Terminate` fuerzan persistencia inmediata. La base de datos guarda el conjunto CMI completo como JSON, además de normalizar puntuación, estado y progreso para informes.

## Sistema de protección

Incluye controles web razonables, no un navegador seguro:

- solicitud de pantalla completa;
- registro de `blur` y `visibilitychange`;
- límite configurable de incidencias;
- número máximo de intentos;
- prerrequisito entre paquetes;
- guardado automático y reanudación;
- registro de eventos.

Una web no puede impedir de forma absoluta que el usuario cierre el navegador o cambie de aplicación. Para exámenes de alta seguridad debe combinarse con ChromeOS administrado, modo quiosco o un navegador de examen.
