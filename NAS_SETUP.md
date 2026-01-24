# 🏠 Despliegue en NAS (Configuración Principal)

Esta guía detalla cómo configurar **Bolus AI** en tu servidor NAS (Synology, QNAP, o cualquier servidor Docker) como tu **instancia principal**.

## 🏗 Arquitectura Híbrida

En esta configuración de Alta Disponibilidad (HA):
1.  **NAS (Principal):** Procesa todas las solicitudes, gestiona el Bot de Telegram y almacena los datos localmente.
2.  **Render (Backup/Guardian):** Monitoriza el NAS. Si el NAS cae, Render sirve como respaldo de emergencia.
3.  **Neon (Nube DB):** Recibe copias de seguridad del NAS cada 4 horas. Render lee de aquí si es necesario.

---

## 1. Requisitos Previos

- **Docker** y **Docker Compose** instalados (o Portainer).
- Acceso SSH o interfaz web para gestionar contenedores.
- Puertos libres: `8000` (API) y `5433` (Postgres Local).

## 2. Instalación con Docker Compose

1.  Copia la carpeta `deploy/nas` a tu servidor.
2.  Renombra `.env.example` a `.env` y rellena las variables (ver abajo).
3.  Ejecuta:
    ```bash
    docker-compose up -d
    ```

## 3. Variables de Entorno (NAS)

Estas variables definen el comportamiento de tu instancia principal.

### 🔌 Conexión y Base de Datos
| Variable | Descripción | Ejemplo |
| :--- | :--- | :--- |
| `POSTGRES_USER` | Usuario DB Local | `admin` |
| `POSTGRES_PASSWORD` | Contraseña DB Local | `tu_password_segura` |
| `POSTGRES_DB` | Nombre DB | `bolus_ai` |
| `DATABASE_URL` | **CRÍTICO**. Cadena de conexión interna para la App. Debe usar el nombre del servicio docker (`db`). | `postgresql://admin:pass@db:5432/bolus_ai` |

### 🌍 URLs y Accesibilidad
| Variable | Descripción | Ejemplo |
| :--- | :--- | :--- |
| `NAS_EXTERNAL_URL` | URL pública de tu NAS (para enlaces en Telegram). | `https://mi-casa.ddns.net:8000` |
| `RENDER_EXTERNAL_URL` | URL de tu instancia de respaldo (para monitorización). | `https://bolus-ai.onrender.com` |
| `BOT_PUBLIC_URL` | URL específica para el Webhook de Telegram. | `https://mi-casa.ddns.net:8000` |

### 🤖 Telegram Bot (Principal)
| Variable | Descripción | Ejemplo |
| :--- | :--- | :--- |
| `ENABLE_TELEGRAM_BOT` | Activa el bot. | `true` |
| `TELEGRAM_BOT_TOKEN` | Token de BotFather. | `123456:ABC-DEF...` |
| `ALLOWED_TELEGRAM_USER_ID` | Tu ID numérico (seguridad). | `12345678` |
| `TELEGRAM_WEBHOOK_SECRET` | Secreto para validar peticiones de Telegram. | `my-secret-token` |

### ☁️ Backup y Sincronización (Neon)
Estas variables controlan el script de backup automático (`backup_to_neon.sh`).

| Variable | Descripción |
| :--- | :--- |
| `DATABASE_URL_NEON` | Cadena de conexión a tu base de datos Neon (Backup). **Diferente a DATABASE_URL**. |
| `CRON_SCHEDULE` | (Opcional) Frecuencia de backup. Default en Dockerfile: cada 4h. |

### 🧠 Inteligencia Artificial (Gemini)
| Variable | Descripción |
| :--- | :--- |
| `GOOGLE_API_KEY` | API Key de Google AI Studio. |
| `VISION_PROVIDER` | `gemini` |
| `GEMINI_MODEL` | `gemini-1.5-flash` (rápido) |

---

## 4. Estrategia de Backup (Safety Valve)

El contenedor `cron` ejecuta un script cada 4 horas que:
1.  Vuelca la base de datos local del NAS.
2.  Compara la fecha del último tratamiento en NAS vs Neon.
3.  **Safety Valve:** Si Neon tiene datos más nuevos que el NAS (significa que usaste Render/Emergencia), **ABORTA** el backup para no sobrescribir datos nuevos con viejos.
4.  Si todo está bien (NAS >= Neon), sube la copia a Neon.

## 5. Mantenimiento

- **Ver logs del bot:** `docker logs bolus_app -f`
- **Ver estado del backup:** `docker logs bolus_cron`
- **Actualizar:**
  ```bash
  docker-compose pull
  docker-compose up -d
  ```
