# Guía de Despliegue en NAS (Asustor/Synology) con Docker

Esta carpeta contiene todo lo necesario para migrar tu Bolus AI desde la nube (Render) a tu NAS local.

## Ventajas de esta Migración

- **Espacio Infinito:** Ya no tendrás el límite de 0.5GB de Neon. Puedes guardar terabytes de datos de IA.
- **Coste Cero:** Aprovechas el hardware que ya tienes encendido.
- **Privacidad:** Tus datos médicos están en tu casa.

## 🛡️ ¿Es seguro? (Evaluación de Riesgos)

**Respuesta corta: SÍ, es totalmente seguro.**

Muchos usuarios tienen miedo de "romper" lo que ya funciona en la nube al tocar el NAS. Aquí te explico por qué **NO hay peligro**:

1. **Aislamiento Total:**
    El NAS crea su propia base de datos vacía (Postgres Local). **No toca ni se conecta** a tu base de datos de Neon (Render) durante la instalación. Son dos mundos separados.

2. **Render sigue vivo:**
    Mientras instalas y pruebas en el NAS, tu app de Render sigue funcionando felizmente. No se "apaga" ni se entera de que estás configurando otro servidor.

3. **El "Script de Sincronización" es unidireccional:**
    El script `sync_to_cloud.py` que hemos creado solo envía datos **DESDE el NAS HACIA Neon**. Nunca borra datos de tu NAS basándose en la nube.
    - *Riesgo:* Si lo configuras mal, podrías escribir datos basura en Neon.
    - *Solución:* Neon tiene "Point-in-Time Recovery" (puedes deshacer cambios de los últimos días) y además hemos puesto protecciones en el script.

**En resumen:** En el peor de los casos, si el NAS explota o no arranca, simplemente lo apagas y sigues usando Render como si nada hubiera pasado.

## Pasos para Instalar en el NAS

### 1. Preparar el NAS

1. Accede a tu NAS (vía SSH o Portainer).
2. Crea una carpeta para el proyecto, por ejemplo: `/volume1/docker/bolus_ai`.
3. Dentro de esa carpeta, crea dos carpetas vacías llamadas `db_data` y `app_data` para asegurar la persistencia.
4. Sube el contenido de **esta carpeta** (`docker-compose.yml`) y el archivo `.env` con tus claves.

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
   
   # (Opcional) Sincronización Automática (Por defecto APAGADO "0")
   # Pon "1" para activar el volcado diario de datos a Neon.
   SYNC_ENABLED=0

   # (Opcional) Puerto de la Base de Datos
   # Cámbialo si el 5432 te da error "Address already in use"
   DB_PORT=5433
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

#### Método B: Vía Consola (Directo con `bolus_migrator`)

*Utiliza este método si tienes problemas de versiones (ej. Neon usa Postgres v16/v17 y el NAS v15). Hemos incluido un contenedor especial (`bolus_migrator`) con herramientas actualizadas para hacer el puente.*

1. **Entra a la Consola**: En Portainer, busca el contenedor `bolus_migrator` -> Icono **Console** (>_) -> Connect.
2. **Ejecuta el Comando Puente**: Copia y pega este comando (editándolo con tus datos). Esto conecta a Neon, chupa los datos y los inyecta directamente en tu NAS mediante una "tubería" (pipe), sin crear archivos intermedios.

   ```bash
   # Sintaxis: pg_dump "URL_ORIGEN_NEON" | psql "URL_DESTINO_LOCAL"
   
   pg_dump "postgres://usuario:pass@ep-neon.../neondb" | psql "postgresql://admin:tu_password_segura@db:5432/bolus_ai"
   ```

   - **Origen (Neon)**: Cópiala de tu dashboard de Neon (Connection String).
   - **Destino (NAS)**: Es la URL interna. Solo cambia `admin` y `tu_password_segura` por lo que pusiste en tu `.env`. Mantén `@db:5432/bolus_ai` tal cual.

3. ¡Listo! Verás pasar muchas líneas de SQL y terminará.

#### Método C: Vía Archivo (Clásico)

Si prefieres subir un archivo `backup.sql` manual:
1. Sube el archivo a la carpeta del NAS donde está el `docker-compose.yml`.
2. Desde la consola de `bolus_migrator` (que ve tus archivos en `/var/lib/postgresql/data` si has montado el volumen, OJO: en este container por defecto NO está montado el volumen de datos para seguridad, así que se recomienda el **Método B** o **A**).
   
   *Nota: Si realmente necesitas usar archivos, es mejor usar el Método A (DBeaver) o configurar un volumen temporal.*

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

Si quieres dormir tranquilo al 100%, hemos incluido un "sidecar" (servicio acompañante) que puede copiar tus datos recientes (30 días) a tu base de datos antigua de Neon cada noche.

El servicio `bolus_sync` ya está instalado pero **viene APAGADO por defecto** para tu seguridad.

### Cómo activarlo

Simplemente cambia la variable de entorno en Portainer:

```bash
SYNC_ENABLED=1
```

Y redeploya el stack. El servicio se despertará cada 24h, comprobará si hay datos nuevos y los subirá a la nube a modo de copia de seguridad.

> **Nota:** Próximamente podrás controlar esto directamente desde los Ajustes de la App.

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

## 8. Próximos Pasos (Roadmap: Panel de Control)

Actualmente, el servicio de sincronización se controla mediante variables de entorno (`SYNC_ENABLED=0/1`). El objetivo final es integrar esto en la interfaz de usuario.

### Plan de Desarrollo Pendiente

1. **Base de Datos (`backend`)**:
    - Crear una tabla `system_settings` para guardar configuraciones globales (no por usuario).
    - Campos: `key` (ej: "sync_enabled"), `value` ("true"), `updated_at`.

2. **API (`backend`)**:
    - Crear endpoints `GET /api/settings/sync` y `POST /api/settings/sync` para leer y modificar el estado.

3. **Script Inteligente (`deploy/nas/sync_to_cloud.py`)**:
    - Modificar el bucle `main()` para que, en lugar de mirar `os.getenv("SYNC_ENABLED")`, haga una consulta a la base de datos local: `SELECT value FROM system_settings WHERE key='sync_enabled'`.
    - Esto permitirá cambiar el comportamiento en tiempo real sin reiniciar el contenedor.

4. **Frontend (`frontend`)**:
    - Crear un nuevo componente en la página de Ajustes (`SettingsPage.jsx`).
    - Añadir un "Toggle Switch" para "Copia de Seguridad en Nube".
    - Mostrar el estado de la última sincronización.
