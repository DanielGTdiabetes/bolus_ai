# ☁️ Despliegue en Render (Backup / Emergency)

Esta guía explica cómo desplegar **Bolus AI** en Render como instancia **backup/emergency**. La instancia recomendada como primary es el NAS local documentado en [NAS_SETUP.md](./NAS_SETUP.md).

> **Seguridad clínica:** Render no convierte Bolus AI en un sistema autónomo. Bolus AI no es un dispositivo médico, no administra insulina y todas las estimaciones son **estimate-only** con revisión humana.

---

## 1. Rol de Render en la arquitectura

```text
NAS = primary
Render = backup/emergency
Hermes Agent → /api/agent/* → Bolus AI core
```

Render debe usarse para contingencia cuando el NAS no esté disponible o para mantener una instancia secundaria controlada. Si habilitas Hermes Agent contra Render, recuerda que la URL de Render suele ser pública y requiere controles estrictos.

| Componente | Rol |
| :--- | :--- |
| **NAS** | Instancia principal recomendada. |
| **Render** | Instancia secundaria para emergencia/backup. |
| **Hermes Agent** | Orquestador conversacional opcional. No es motor médico. |
| **Agent API** | API interna autenticada, read-only / estimate-only. |

---

## 2. Preparación del repositorio

Asegúrate de tener el código en un repositorio de GitHub o GitLab. Render se conectará a este repositorio para descargar y ejecutar la aplicación.

---

## 3. Crear el servicio web (backend + frontend)

Bolus AI está configurado para ejecutarse como un único servicio que sirve tanto el servidor FastAPI como el frontend construido.

1. Inicia sesión en [Render.com](https://render.com/).
2. Haz clic en **New +** y selecciona **Web Service**.
3. Conecta tu repositorio.
4. Configura los campos principales:

| Campo | Valor recomendado |
| :--- | :--- |
| **Name** | `bolus-ai` o nombre equivalente |
| **Region** | La más cercana a tu uso principal |
| **Language** | `Python` |
| **Root Directory** | Raíz del proyecto |
| **Build Command** | `chmod +x build_render.sh && ./build_render.sh` |
| **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Plan** | `Starter` o superior según necesidad |
| **AutoDeploy** | `No`, recomendado para controlar cambios |

El archivo `render.yaml` del repositorio ya documenta `autoDeploy: false`, `healthCheckPath: /healthz`, runtime Python y disco persistente.

---

## 4. Variables de entorno en Render

Configura las variables desde **Environment** en Render. No subas secretos al repositorio.

### Runtime y persistencia

| Variable | Obligatoria | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `PYTHON_VERSION` | Sí | Versión Python usada por Render. | `3.11.0` |
| `NODE_VERSION` | Sí | Versión Node para construir frontend. | `20.10.0` |
| `DATA_DIR` | Sí | Ruta del disco persistente. | `/var/data` |
| `PORT` | Render | Render la inyecta automáticamente. | `$PORT` |

### Seguridad de aplicación

| Variable | Obligatoria | Descripción |
| :--- | :--- | :--- |
| `JWT_SECRET` | Sí | Genera un valor largo y único en Render. |
| `APP_SECRET_KEY` | Sí | Clave larga para secretos internos/cifrado. |

### Nightscout (si aplica)

| Variable | Obligatoria | Descripción |
| :--- | :--- | :--- |
| `NIGHTSCOUT_URL` | Si usas Nightscout | URL de tu instancia Nightscout. |
| `NIGHTSCOUT_API_SECRET` | Según configuración | Secreto/API secret si tu Nightscout lo requiere. |

### Hermes Agent / Agent API (solo si se habilita en emergencia)

| Variable | Obligatoria | Descripción |
| :--- | :--- | :--- |
| `AGENT_API_TOKEN` | Solo si habilitas `/api/agent/*` | Token bearer interno. Usa un valor distinto al del NAS. |
| `AGENT_ALLOWED_IPS` | Recomendado | IPs permitidas separadas por comas si puedes fijar origen. |

Recomendación: no habilites la Agent API en Render salvo que tengas un caso de emergencia claro y puedas proteger token, IPs y acceso HTTPS.

### Telegram (opcional)

| Variable | Obligatoria | Descripción |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Si activas bot | Token de BotFather. |
| `TELEGRAM_ALLOWED_USER` | Si tu despliegue lo usa | ID autorizado. |
| `ALLOWED_TELEGRAM_USER_ID` | Si tu despliegue lo usa | Variable alternativa usada en despliegues NAS/locales. |
| `TELEGRAM_WEBHOOK_SECRET` | Recomendado | Secreto de webhook. |

### Visión IA (opcional)

| Variable | Obligatoria | Descripción |
| :--- | :--- | :--- |
| `GOOGLE_API_KEY` | Si usas Gemini | API key de Google AI Studio. |
| `OPENAI_API_KEY` | Si usas OpenAI | API key alternativa si está soportada/configurada. |
| `VISION_PROVIDER` | Si usas visión | Proveedor seleccionado. |

---

## 5. Disco persistente

Si usas un plan con disco persistente:

1. Ve a la pestaña **Disk**.
2. Haz clic en **Add Disk**.
3. Configura:

| Campo | Valor |
| :--- | :--- |
| **Name** | `bolus-data` |
| **Mount Path** | `/var/data` |
| **Size** | `1 GB` o el tamaño que necesites |

`DATA_DIR` debe apuntar al mismo mount path.

---

## 6. Verificación básica

Una vez desplegado, comprueba:

```bash
curl -s https://TU-SERVICIO.onrender.com/healthz
```

Si habilitaste Agent API en Render:

```bash
curl -s \
  -H "Authorization: Bearer ${AGENT_API_TOKEN}" \
  https://TU-SERVICIO.onrender.com/api/agent/status
```

El endpoint `/api/agent/*` debe permanecer bloqueado si `AGENT_API_TOKEN` no está configurado.

---

## 7. Operación como backup/emergency

- Mantén AutoDeploy desactivado si quieres controlar cuándo entra una versión nueva en la instancia de emergencia.
- Usa secretos distintos a los del NAS cuando sea posible.
- Documenta cuándo se usa Render en lugar de NAS para evitar confusión operativa.
- No uses Render para automatizar decisiones terapéuticas ni administración de insulina.

---

## 8. Tips adicionales

- **Acceso inicial:** cambia cualquier credencial por defecto tras el primer acceso.
- **Telegram:** consulta [docs/TELEGRAM_SETUP.md](./docs/TELEGRAM_SETUP.md) si decides activar el bot.
- **Nightscout:** puedes configurar la URL por variables o desde la interfaz si el flujo actual lo permite.
- **Análisis de fotos:** configura un proveedor de visión solo si vas a usar esa capacidad.
