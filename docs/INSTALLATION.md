# Instalación automática

## Requisitos

Servidor Linux x86_64/ARM64 con Debian, Ubuntu, Fedora, Rocky/Alma o derivado, acceso root y puertos 80/443 disponibles. El instalador instala Docker si no está presente.

## Instalación con dominio y HTTPS automático

Primero crea un registro DNS A/AAAA que apunte al servidor. Después:

```bash
curl -fsSL https://raw.githubusercontent.com/atreyu1968/scorm-classroom-bridge/main/install.sh | sudo bash -s -- --domain scorm.ejemplo.es
```

Caddy obtiene y renueva automáticamente el certificado TLS.

## Instalación provisional por IP/HTTP

```bash
curl -fsSL https://raw.githubusercontent.com/atreyu1968/scorm-classroom-bridge/main/install.sh | sudo bash
```

No se recomienda HTTP para uso real con alumnado.

## Definir credenciales durante la instalación

```bash
curl -fsSL https://raw.githubusercontent.com/atreyu1968/scorm-classroom-bridge/main/install.sh | sudo bash -s -- \
  --domain scorm.ejemplo.es \
  --admin-user profesor \
  --admin-password 'UnaClaveLargaYUnica'
```

Si no se indica contraseña, el instalador genera una aleatoria y la muestra al terminar.

## Actualización

```bash
cd /opt/scorm-classroom-bridge
sudo bash upgrade.sh
```

Antes de actualizar se crea una copia de seguridad.

## Copia de seguridad

```bash
cd /opt/scorm-classroom-bridge
sudo bash backup.sh
```

## Desinstalación

Conservar datos:

```bash
sudo bash uninstall.sh
```

Borrar también los datos:

```bash
sudo bash uninstall.sh --purge-data
```
