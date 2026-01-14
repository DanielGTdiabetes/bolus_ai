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

### 3. Despliegue con Portainer (Método Recomendado: GitOps)

La forma más profesional y limpia. Si actualizas algo en GitHub, tu NAS lo baja solo.

1. Entra a Portainer -> **Stacks** -> **Add stack**.
2. Selecciona la opción **Repository** (pestaña superior).
3. Rellena los datos:
   - **Name**: `bolus_stack`
   - **Repository URL**: `https://github.com/DanielGTdiabetes/bolus_ai` (o tu URL)
   - **Compose path**: `deploy/nas/docker-compose.yml` (⚠️ Ruta exacta dentro del repo)
   - **Automatic Updates**: Actívalo si quieres que se actualice solo al hacer push.
4. En **Environment variables**, añade tus secretos manualmente.

   ⚠️ **MUY IMPORTANTE (Persistencia de Datos):**
   Como Portainer descarga el código en una carpeta temporal, debes decirle dónde guardar `postgres_data` para no perder la base de datos si reinicias el stack.

   Añade estas variables apuntando a carpetas reales de tu NAS:

   ```bash
   # Rutas ABSOLUTAS en tu NAS (OBLIGATORIO)
   DB_DATA_PATH=/volume1/docker/bolus_ai/db_data
   APP_DATA_PATH=/volume1/docker/bolus_ai/app_data
   
   # Puerto Web (Opcional, por defecto 8000)
   # Si el 8000 está ocupado, cámbialo aquí (ej: 8085)
   APP_PORT=8000

   # --- Variables que debes COPIAR de Render ---
   TELEGRAM_BOT_TOKEN=...
   ALLOWED_TELEGRAM_USER_ID=...
   
   # Frontend / URLs Públicas
   # En el NAS, esta es la URL pública si usas Tunnel o tu IP local.
   RENDER_EXTERNAL_URL=http://tu-nas-ip:8000
   
   # IA y Configuración (Copia solo las que uses)
   OPENAI_API_KEY=...
   GOOGLE_API_KEY=...
   VISION_PROVIDER=...
   GEMINI_MODEL=...
   TELEGRAM_DEFAULT_CHAT_ID=...
   TELEGRAM_WEBHOOK_SECRET=...
   NUTRITION_INGEST_KEY=...
   
   # Claves de Seguridad (míralas en Render o crea nuevas largas)
   JWT_SECRET=...
   APP_SECRET_KEY=...

   # --- Variables NUEVAS para el NAS ---
   POSTGRES_USER=admin
   POSTGRES_PASSWORD=tu_password_segura
   # Esta URL es interna, cópiala tal cual cambiando la contraseña:
   DATABASE_URL=postgresql://admin:tu_password_segura@db:5432/bolus_ai
   
   # (Opcional) Para Modo Emergencia (La URL de Neon que usabas antes)
   CLOUD_DATABASE_URL=postgresql+asyncpg://...@neon.tech/...
   ```

5. Pulsa **Deploy the stack**.

¡Listo! El script de sincronización `sync_to_cloud.py` ya estará dentro del contenedor listo para usarse.

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

#### Opción A: Tailscale (Gratis y Segura - Recomendada)

1. **En el NAS:** Instala "Tailscale" desde el **App Central** de Asustor.
2. **En el iPhone:** Instala la App de Tailscale y actívala (interruptor ON).
3. **Navegación:** Ahora, abre tu navegador Bluetooth (ej. Bluefy) y entra a la IP del NAS (`http://192.168.1.XX:8000`) como si estuvieras en casa. Tailscale hace el puente invisible por debajo.

#### Opción B: Cloudflare Tunnel (Sin instalar nada en el iPhone)

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

## 7. Preguntas Frecuentes (FAQ)

### ¿Necesito instalar Postgres o SQLite en mi NAS?

**NO.** Rotundamente no.
Esa es la magia de Docker. En el archivo `docker-compose.yml` verás esto:

```yaml
  db:
    image: postgres:15-alpine
```

Esto le dice a tu NAS: *"Descarga un servidor Postgres oficial, arráncalo y conéctalo a mi app"*.
Todo ocurre **dentro** de un contenedor aislado. Tu NAS ni se entera de que tiene Postgres instalado. Lo único que necesitas tener instalado es **Docker** (que viene con Portainer).

### ¿Si borro el Stack en Portainer pierdo mis datos?

**Depende.**

- Si configuraste `DB_DATA_PATH` apuntando a una carpeta de tu NAS (como indicamos en el paso 3): **Tus datos están seguros**. Puedes borrar y reinstalar los contenedores mil veces.
- Si no pusiste nada: Se guardan en un volumen interno de Docker que podría borrarse si haces una limpieza profunda.
**Recomendación:** Usa siempre rutas fijas (`/volume1/docker/bolus_ai/...`).
