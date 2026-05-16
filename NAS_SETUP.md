# 🏠 Despliegue en NAS (Primary)

Esta guía detalla cómo configurar **Bolus AI** en un servidor NAS o servidor Docker local como **instancia primary**.

Bolus AI debe seguir siendo el motor clínico central. Si integras **Hermes Agent**, Hermes debe conectarse a Bolus AI mediante `/api/agent/*` como capa conversacional/orquestadora, sin administración automática de insulina.

> **Seguridad clínica:** Bolus AI no es un dispositivo médico. La Agent API es **read-only / estimate-only / human-in-the-loop**. No automatices administración de insulina desde NAS, Hermes, Telegram, Nightscout ni otros sistemas.

---

## 🏗 Arquitectura NAS primary + Render backup

```text
Hermes Agent (opcional, red local)
    ↓ Bearer token
/api/agent/* en NAS
    ↓
Bolus AI core en NAS (primary)
    ├─ FastAPI backend
    ├─ Frontend React/Vite
    ├─ Postgres local
    ├─ Nightscout / fuente de glucosa configurada
    └─ Backup opcional hacia Neon/Render

Render = instancia backup/emergency
```

| Componente | Rol |
| :--- | :--- |
| **NAS** | Instancia principal recomendada. Procesa solicitudes, sirve frontend/backend y mantiene datos locales. |
| **Hermes Agent** | Opcional. Capa conversacional local que llama a `/api/agent/*`. No es motor médico. |
| **Nightscout** | Fuente/integración de datos según configuración. |
| **Render** | Backup/emergency, no primary. |
| **Neon u otra DB cloud** | Backup/failover si se configura. |

---

## 1. Requisitos previos

- Docker y Docker Compose instalados, o Portainer.
- Acceso SSH o interfaz web para gestionar contenedores.
- Puertos libres, habitualmente `8000` para la aplicación y `5433` para Postgres expuesto en el host.
- Carpeta persistente para base de datos y datos de aplicación.
- Credenciales Nightscout si vas a consultar glucosa desde Nightscout.
- Token largo y aleatorio si vas a habilitar Hermes Agent mediante `/api/agent/*`.

---

## 2. Instalación con Docker Compose

1. Copia la carpeta `deploy/nas` a tu servidor.
2. Renombra `.env.example` a `.env` y rellena las variables necesarias.
3. Revisa que las rutas `DB_DATA_PATH` y `APP_DATA_PATH` existan o puedan crearse.
4. Ejecuta:

```bash
docker-compose up -d
```

5. Comprueba logs:

```bash
docker compose logs --tail=100 db
docker compose logs --tail=100 backend
```

> Nota: si tu `docker-compose.yml` no pasa explícitamente `AGENT_API_TOKEN`/`AGENT_ALLOWED_IPS` al contenedor backend, añádelas al entorno del servicio backend antes de esperar que `/api/agent/*` esté habilitado. La API queda bloqueada si `AGENT_API_TOKEN` no llega al proceso FastAPI.

---

## 3. Variables de entorno (NAS)

### 🔌 Base de datos local

| Variable | Obligatoria | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `POSTGRES_USER` | Sí | Usuario de Postgres local. | `admin` |
| `POSTGRES_PASSWORD` | Sí | Contraseña de Postgres local. | `tu_password_segura` |
| `POSTGRES_DB` | Sí | Nombre de la base de datos. | `bolus_ai` |
| `DATABASE_URL` | Sí | Cadena interna usada por FastAPI. Debe apuntar al servicio Docker `db`. | `postgresql://admin:pass@db:5432/bolus_ai` |

### 📁 Persistencia y puertos

| Variable | Obligatoria | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `DB_DATA_PATH` | Sí | Ruta persistente para Postgres en el NAS. | `/volume1/docker/bolus_ai/db_data` |
| `APP_DATA_PATH` | Sí | Ruta persistente para datos de app. | `/volume1/docker/bolus_ai/app_data` |
| `DATA_DIR` | Sí | Ruta interna de datos para la app. | `/app/backend/data` |
| `APP_PORT` | No | Puerto host para Bolus AI. | `8000` |
| `DB_PORT` | No | Puerto host para Postgres si lo expones. | `5433` |

### 🌍 URLs y accesibilidad

| Variable | Obligatoria | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `NAS_EXTERNAL_URL` | Recomendado | URL local o pública de la instancia NAS. | `https://mi-casa.example.net` |
| `RENDER_EXTERNAL_URL` | Si usas backup | URL de Render backup/emergency. | `https://bolus-ai.onrender.com` |
| `BOT_PUBLIC_URL` | Si usas Telegram webhook | URL usada por Telegram para webhooks. | `https://mi-casa.example.net` |
| `FRONTEND_ORIGIN` | Recomendado | Origen permitido del frontend si tu despliegue lo requiere. | `https://mi-casa.example.net` |

### 🔐 Seguridad de aplicación

| Variable | Obligatoria | Descripción |
| :--- | :--- | :--- |
| `APP_SECRET_KEY` | Sí | Clave larga para cifrado/secretos internos de la app. |
| `JWT_SECRET` | Sí | Clave larga para firmar sesiones/JWT. |

### 🤖 Hermes Agent / Agent API

| Variable | Obligatoria | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `AGENT_API_TOKEN` | Solo si habilitas Hermes | Bearer token interno, largo y aleatorio. Si falta, `/api/agent/*` responde `503`. | `openssl rand -hex 32` |
| `AGENT_ALLOWED_IPS` | No | Lista de IPs permitidas separadas por comas. | `192.168.1.50,127.0.0.1` |

Recomendaciones:

- Habilita Hermes Agent preferentemente solo en la red local.
- Usa un token distinto de cualquier token Nightscout, Telegram o JWT.
- No expongas `/api/agent/*` públicamente salvo que controles red, TLS, token e IPs.

### 📡 Nightscout

| Variable | Obligatoria | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `NIGHTSCOUT_URL` | Si usas Nightscout | URL base de Nightscout. | `https://tu-nightscout.example.com` |
| `NIGHTSCOUT_API_SECRET` | Según permisos | Secreto/API secret si tu configuración lo requiere. | `...` |

La Agent API no expone estos secretos y no los necesita en Hermes Agent.

### 🤖 Telegram Bot (opcional)

| Variable | Obligatoria | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `ENABLE_TELEGRAM_BOT` | No | Activa el bot si está configurado. | `true` |
| `TELEGRAM_BOT_TOKEN` | Si activas bot | Token de BotFather. | `123456:ABC...` |
| `TELEGRAM_DEFAULT_CHAT_ID` | Si activas bot | Chat ID por defecto. | `123456789` |
| `ALLOWED_TELEGRAM_USER_ID` | Recomendado | ID permitido para reducir abuso. | `123456789` |
| `TELEGRAM_WEBHOOK_SECRET` | Recomendado | Secreto para validar webhooks. | `valor_largo` |

### 🧠 Visión IA (opcional)

| Variable | Obligatoria | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `VISION_PROVIDER` | Si usas visión | Proveedor configurado. | `gemini` |
| `GOOGLE_API_KEY` | Si usas Gemini | API key de Google AI Studio. | `...` |
| `GEMINI_MODEL` | No | Modelo Gemini rápido. | `gemini-1.5-flash` |
| `GEMINI_MODEL_PRO` | No | Modelo Gemini alternativo/pro. | `gemini-1.5-pro` |

### ☁️ Backup y sincronización (opcional)

| Variable | Obligatoria | Descripción |
| :--- | :--- | :--- |
| `DATABASE_URL_NEON` | Si usas backup Neon | Cadena de conexión a la DB cloud de backup. Debe ser distinta de `DATABASE_URL`. |
| `CRON_SCHEDULE` | No | Frecuencia del backup si el contenedor/script la soporta. |
| `SYNC_ENABLED` | No | Activa sincronización si tu despliegue usa ese mecanismo. |
| `SYNC_INTERVAL_SECONDS` | No | Intervalo de sincronización si aplica. |

---

## 4. Verificación de Agent API

Con `AGENT_API_TOKEN` configurado y presente en el backend:

```bash
curl -s \
  -H "Authorization: Bearer ${AGENT_API_TOKEN}" \
  http://NAS_HOST:8000/api/agent/status
```

Si el token no está configurado, el comportamiento esperado es bloqueo seguro (`503`). Si el token es incorrecto, debe rechazarse la petición.

---

## 5. Estrategia de backup

Si se configura el contenedor/script de backup:

1. Vuelca la base de datos local del NAS.
2. Compara el estado local con la base cloud cuando el flujo lo soporta.
3. Evita sobrescrituras peligrosas si el backup/cloud contiene datos más recientes.
4. Sube la copia solo si la comprobación es segura.

Mantén la instancia NAS como fuente primary y usa Render como contingencia, no como sustituto silencioso permanente.

---

## 6. Mantenimiento

- Ver logs de aplicación:

```bash
docker compose logs -f backend
```

- Ver logs de backup:

```bash
docker compose logs -f backup
```

- Actualizar contenedores:

```bash
docker-compose pull
docker-compose up -d
```

---

## 7. Recordatorio de seguridad

- No publiques `.env` ni secretos.
- Cambia credenciales por defecto en el primer acceso.
- Mantén la Agent API protegida con token y, si es posible, IP allowlist.
- No conectes Hermes Agent a mecanismos de administración automática de insulina.
