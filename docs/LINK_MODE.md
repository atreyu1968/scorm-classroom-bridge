# Modo por enlace sin Google

Este modo está diseñado para dominios educativos donde el alumnado no puede autorizar aplicaciones externas con su cuenta Google. No utiliza OAuth para identificar al alumno.

## Tipos de acceso

- `/student/access`: acceso mediante código de alumno y PIN opcional.
- `/u/<token>`: enlace personal permanente del alumno. Muestra sus asignaciones actuales.
- `/a/<token>`: enlace directo a una actividad.
- `/e/<token>`: enlace directo a un examen.
- `/admin`: panel local del profesorado.

Los tokens se generan con aleatoriedad criptográfica y no contienen el nombre, correo ni otros datos del alumno.

## Flujo recomendado

1. El profesor entra en `/admin` con `ADMIN_USERNAME` y `ADMIN_PASSWORD`.
2. Sube los paquetes SCORM a la biblioteca.
3. Crea alumnado manualmente o importa un CSV.
4. Entrega a cada alumno su código o enlace personal `/u/...`.
5. En **Asignaciones**, selecciona un SCORM, un grupo o alumnos concretos y configura las fechas y controles.
6. El sistema crea un token diferente para cada alumno y asignación.
7. El alumno abre el enlace desde Classroom, correo, QR u otra vía. No se le solicita autenticación de Google.
8. El runtime SCORM guarda estado, progreso, nota, intentos e incidencias en el servidor.

## PIN

El PIN es opcional. Si se utiliza, se almacena únicamente como hash. El panel no puede recuperar un PIN existente: puede reemplazarlo por uno nuevo.

Si se marca **Exigir PIN** en una asignación, solo se genera para alumnos que ya tengan PIN configurado.

## Vinculación de dispositivo

Una asignación puede vincularse al primer navegador que la inicia. El servidor guarda un hash del identificador aleatorio del navegador, no una huella biométrica ni un fingerprint invasivo.

En modo examen esta opción se activa automáticamente. Si el alumno cambia de equipo, el profesor puede usar **Reset dispositivo**.

## Modo examen

Por defecto:

- 1 intento si no se especifica otro valor;
- pantalla completa solicitada;
- vinculación al primer dispositivo;
- registro de pérdidas de foco;
- botón **Entregar y salir**.

Las restricciones del navegador siguen siendo aplicables: una aplicación web no puede impedir físicamente apagar el equipo, cerrar el navegador o cambiar de aplicación.

## CSV de alumnado

Se admiten las columnas:

```text
nombre,grupo,email,pin,identificador
```

Solo `nombre` es imprescindible. Si no se indica identificador, el sistema genera un código. Si no se indica email, se crea un identificador interno no utilizable como correo real.

Consulta `docs/alumnos_ejemplo.csv`.

## Cursos de varias lecciones (v3)

El acceso personal del alumnado también muestra los cursos en los que está matriculado. Un curso puede encadenar varios ZIP SCORM como lecciones. En modo secuencial, las lecciones posteriores permanecen bloqueadas hasta cumplir los requisitos de las anteriores. El profesor puede definir obligatoriedad, exigencia de aprobado y nota mínima por lección.

## Bajas y archivo de alumnado (v3)

- **Desactivar**: impide temporalmente el acceso.
- **Archivar**: marca una baja conservando intentos, notas, matrículas y asignaciones.
- **Restaurar**: reactiva un alumno archivado.
- **Eliminar definitivamente**: borra el alumno y todo su historial; requiere confirmación explícita.
