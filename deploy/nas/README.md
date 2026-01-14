# Guía de Despliegue en NAS (Asustor/Synology) con Docker

Esta carpeta contiene todo lo necesario para migrar tu Bolus AI desde la nube (Render) a tu NAS local.

## Ventajas de esta Migración

- **Espacio Infinito:** Ya no tendrás el límite de 0.5GB de Neon. Puedes guardar terabytes de datos de IA.
- **Coste Cero:** Aprovechas el hardware que ya tienes encendido.
- **Privacidad:** Tus datos médicos están en tu casa.

## Pasos para Instalar en el NAS

### 1. Preparar el NAS

1. Accede a tu NAS (vía SSH o Portainer).
2. Crea una carpeta para el proyecto, por ejemplo: `/volume1/docker/bolus_ai`.
3. Sube el contenido de **esta carpeta** (`docker-compose.yml`) y el archivo `.env` con tus claves.

### 2. Configurar Variables (.env)

Crea un archivo llamado `.env` en la misma carpeta del NAS con este contenido (rellena con tus datos reales):

```bash
# Credenciales para la nueva Base de Datos Local
POSTGRES_USER=admin
POSTGRES_PASSWORD=tu_contraseña_segura_nas

# Tus claves actuales (Cópialas de Render o tu PC)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
ALLOWED_TELEGRAM_USER_ID=tu_id_telegram
NIGHTSCOUT_URL=https://tu-sitio.nightscout.net
NIGHTSCOUT_API_SECRET=tu_api_token
OPENAI_API_KEY=sk-proj-...
```

### 3. Despliegue con Portainer (Recomendado)

Si usas Portainer en tu NAS, es aún más fácil:

1. Entra a Portainer y ve a la sección **Stacks**.
2. Pulsa en **Add stack**.
3. Nombre: `bolus_stack` (o el que quieras).
4. En el editor **Web editor**, pega el contenido del archivo `docker-compose.yml` de esta carpeta.
   - *Nota:* Como la ruta `build: ../../` no funciona directamente en el editor web de Portainer si no clonas el repo git, te recomiendo cambiar la línea `build: ...` por `image: ghcr.io/tu-usuario/bolus_ai:latest` si tienes imagen, o mejor aún:
   - **Opción Pro:** Conecta el Stack a tu **Repositorio GitHub** (pestaña 'Repository' en Portainer).
     - Repo URL: `https://github.com/usuario/bolus_ai`
     - Path: `deploy/nas/docker-compose.yml`
     - Automatic Updates: ON.
5. En la sección **Environment variables** (abajo del todo), añade tus claves una a una (`POSTGRES_PASSWORD`, `TELEGRAM_BOT_TOKEN`, etc.) o carga el archivo `.env`.
6. Pulsa **Deploy the stack**.

### 4. Migrar tus Datos (Neon -> NAS)

Tienes dos formas de hacerlo. El método visual suele ser el más fácil desde Windows.

#### Método A: Visual con DBeaver (Recomendado)

1. Instala **DBeaver** (gratis) en tu PC.
2. Crea dos conexiones:
   - **Origen:** Conecta a tu base de datos **Neon** (copia los datos de tu Dashboard de Neon).
   - **Destino:** Conecta a tu **NAS** (IP del NAS, Puerto 5432, User: `admin`, Pass: la que pusiste).
3. En DBeaver, haz clic derecho en la base de datos de Neon -> **Tools** -> **Backup**. Guarda el archivo en tu PC.
4. Ahora, clic derecho en la base de datos del NAS -> **Tools** -> **Restore**. Selecciona el archivo que acabas de bajar.
5. ¡Listo! Tus datos se copiarán automáticamente.

#### Método B: Vía Consola y Archivo

1. **Paso 1: Conseguir el archivo (En tu PC)**
   Desde tu ordenador, usa DBeaver o la terminal para descargar tus datos de Neon a un archivo `backup.sql`.

   ```powershell
   pg_dump "postgres://usuario:pass@ep-neon.../neondb" > backup.sql
   ```

2. **Paso 2: Subir al NAS**
   Sube ese archivo `backup.sql` a la carpeta de tu NAS donde has puesto el `docker-compose.yml`. Al estar en la misma carpeta que el volumen, el Docker podrá "verlo".

3. **Paso 3: Importar (Desde Portainer)**
   Ahora que el archivo está en el NAS:
   - Ve a tu contenedor `bolus_db` en Portainer -> Icono **Console** (>_) -> Connect.
   - Ejecuta este comando mágico:

     ```bash
     psql -U admin -d bolus_ai < /var/lib/postgresql/data/backup.sql
     ```

     *(Nota: `/var/lib/postgresql/data` es la ruta interna donde el contenedor ve los archivos de tu carpeta del NAS).*

## Notas Importantes

- La base de datos guardará sus archivos en la carpeta `./postgres_data` dentro de donde pongas el docker-compose. **No borres esa carpeta** o perderás tus datos.
- Las copias de seguridad de IA (JSONL) se guardarán en `./app_data/archive`.

## 5. Acceso a la Aplicación

Una vez arrancado, ¿cómo entras?

### Desde Casa (WiFi)

Abre tu navegador y escribe la IP de tu NAS y el puerto 8000:
`http://192.168.1.XX:8000`
*(Sustituye 192.168.1.XX por la IP real de tu NAS)*

### Desde la Calle (4G / 5G)

Al estar en tu casa, no es accesible desde internet por defecto. Tienes dos opciones para entrar desde tu iPhone (usando tu navegador compatible con Bluetooth):

**Opción A: Tailscale (Gratis y Segura - Recomendada)**

1. **En el NAS:** Instala "Tailscale" desde el **App Central** de Asustor.
2. **En el iPhone:** Instala la App de Tailscale y actívala (interruptor ON).
3. **Navegación:** Ahora, abre tu navegador Bluetooth (ej. Bluefy) y entra a la IP del NAS (`http://192.168.1.XX:8000`) como si estuvieras en casa. Tailscale hace el puente invisible por debajo.

**Opción B: Cloudflare Tunnel (Sin instalar nada en el iPhone)**
Si no quieres instalar la app de Tailscale:

1. Configura un **Cloudflare Tunnel** en el NAS.
2. Tendrás una web real (ej: `https://mi-glucosa.com`).
3. Podrás entrar desde tu navegador sin activar nada antes. Requiere comprar un dominio (~10€/año).

## 6. Respaldo Automático en Nube (Cold Standby)

Si quieres dormir tranquilo al 100%, puedes configurar que tu NAS envíe una copia de tus datos recientes (30 días) a tu base de datos antigua de Neon (Render) cada noche. Así, si tu NAS explota, puedes encender Render y seguir como si nada.

### Pasos

1. **Edita el archivo .env** del NAS y añade la conexión a Neon:

   ```bash
   CLOUD_DATABASE_URL=postgresql://usuario:pass@ep-neon.../neondb
   ```

2. **Programar Tarea (Cron):**
   Configura una tarea programada en tu NAS (Task Scheduler en Synology/Asustor) para que se ejecute cada noche (ej: 04:00 AM) con este comando:

   ```bash
   docker exec bolus_app python /app/deploy/nas/sync_to_cloud.py
   ```

¡Hecho! Tu NAS trabajará para ti en casa, y Neon será tu seguro de vida en la nube.
