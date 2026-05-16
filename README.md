# 🩸 Bolus AI

Bolus AI es el **motor clínico central** de apoyo para diabetes tipo 1. Ejecuta el cálculo de estimaciones de bolo, consulta contexto glucémico y mantiene integraciones como Nightscout dentro de una aplicación FastAPI + React/Vite.

> **Uso seguro:** Bolus AI no es un dispositivo médico, no sustituye criterio clínico profesional y no debe usarse para administración autónoma de insulina. Todas las salidas son **estimate-only**, requieren revisión humana y deben interpretarse como apoyo a la decisión.

---

## 📚 Navegación

| Área | Documento |
| :--- | :--- |
| Manual funcional | [Manual de usuario](./docs/MANUAL_USUARIO.md) |
| API interna para Hermes Agent | [Agent API](./docs/AGENT_API.md) |
| Despliegue primary en NAS | [NAS setup](./NAS_SETUP.md) |
| Despliegue backup/emergency en Render | [Render setup](./RENDER_SETUP.md) |
| Bot de Telegram | [Guía del bot](./README_BOT.md) |
| Gestión de usuarios | [Manual de gestión de usuarios](./USER_AUTH_GUIDE.md) |
| Seguridad | [Security](./docs/SECURITY.md) |

---

## ⚠️ Advertencias clínicas y alcance

- **No medical device:** el proyecto no está validado ni certificado como dispositivo médico.
- **No autonomous insulin delivery:** no administra insulina ni debe conectarse a flujos que administren insulina automáticamente.
- **Estimate-only:** las estimaciones de bolo son cálculos de apoyo y pueden ser incompletas o incorrectas si los datos de entrada lo son.
- **Read-only para agentes:** la API interna `/api/agent/*` permite consultar contexto y pedir estimaciones, pero no registra tratamientos ni sube tratamientos a Nightscout.
- **Human-in-the-loop:** una persona usuaria/cuidadora debe revisar glucosa, IOB/COB, carbohidratos, sensibilidad, ratios, alertas y contexto antes de cualquier decisión terapéutica.

---

## 🏗 Arquitectura actual

Bolus AI separa el **motor clínico** de la **capa conversacional/orquestadora**:

```text
Hermes Agent
    ↓
API interna segura /api/agent/*
    ↓
Bolus AI core
    ├─ FastAPI backend
    ├─ Motor de estimación de bolo
    ├─ Integración Nightscout / fuentes de glucosa configuradas
    └─ Frontend React/Vite
```

### Componentes principales

| Componente | Responsabilidad |
| :--- | :--- |
| **Bolus AI core** | Motor central. Calcula estimaciones, consulta contexto glucémico y aplica la lógica clínica existente. |
| **Hermes Agent** | Capa conversacional/orquestador externo. Traduce preguntas del usuario en llamadas controladas a `/api/agent/*`. **No es el motor médico**. |
| **Agent API** | Superficie interna segura para estado, contexto, glucosa actual y estimación de bolo. Usa bearer token obligatorio. |
| **FastAPI backend** | API de aplicación, autenticación, integraciones y servicios internos. |
| **React/Vite frontend** | Interfaz web de usuario. |
| **Nightscout** | Integración de datos glucémicos y ecosistema diabetes según configuración del usuario. |
| **NAS primary** | Instancia principal recomendada, local y controlada por el usuario. |
| **Render backup/emergency** | Instancia secundaria para contingencia, no primary. |

---

## 🤖 Hermes Agent Integration

Hermes Agent se integra con Bolus AI mediante una API interna y autenticada. La integración está diseñada para conversación y orquestación, manteniendo la lógica clínica dentro de Bolus AI.

### Flujo de datos

```text
1. Usuario pregunta a Hermes Agent
2. Hermes Agent solicita estado/contexto a Bolus AI
3. Bolus AI consulta sus fuentes configuradas y devuelve contexto resumido
4. Si el usuario pide una estimación, Hermes llama a /api/agent/bolus/estimate
5. Bolus AI devuelve una estimación sin persistir tratamiento
6. Hermes muestra resultado y advertencias
7. La persona decide manualmente fuera del sistema
```

### Separación de responsabilidades

| Permitido en Hermes Agent | Permanece en Bolus AI | Prohibido para Hermes Agent |
| :--- | :--- | :--- |
| Conversación con el usuario | Cálculo de estimación de bolo | Administrar insulina |
| Orquestar llamadas a `/api/agent/*` | Lectura de contexto clínico configurado | Decidir tratamientos de forma autónoma |
| Mostrar resultados y advertencias | Reglas y servicios clínicos existentes | Guardar tratamientos automáticamente |
| Pedir confirmaciones humanas | Integración Nightscout del backend | Subir tratamientos a Nightscout desde Agent API |

### Endpoints actuales

| Método | Endpoint | Uso |
| :--- | :--- | :--- |
| `GET` | `/api/agent/status` | Estado básico de la aplicación y disponibilidad de la Agent API. |
| `GET` | `/api/agent/context` | Contexto resumido para un agente conversacional. |
| `GET` | `/api/agent/glucose/current` | Glucosa actual normalizada a `mg/dL` desde la fuente configurada. |
| `POST` | `/api/agent/bolus/estimate` | Estimación de bolo sin persistencia y sin subida a Nightscout. |

Consulta detalles, payloads y ejemplos en [docs/AGENT_API.md](./docs/AGENT_API.md).

---

## 🔐 Seguridad de la Agent API

La API `/api/agent/*` está cerrada si no se configura un token interno.

| Variable | Obligatoria | Descripción |
| :--- | :--- | :--- |
| `AGENT_API_TOKEN` | Sí, para habilitar `/api/agent/*` | Token bearer largo, aleatorio y secreto. |
| `AGENT_ALLOWED_IPS` | No | Lista separada por comas de IPs autorizadas, por ejemplo la IP del mini PC que ejecuta Hermes Agent. |

Ejemplo de llamada:

```bash
curl -s \
  -H "Authorization: Bearer ${AGENT_API_TOKEN}" \
  http://bolus-ai.local:8000/api/agent/status
```

Buenas prácticas:

- No publiques `AGENT_API_TOKEN` en GitHub, logs, capturas ni tickets.
- Mantén `/api/agent/*` dentro de una red privada o túnel controlado.
- Usa `AGENT_ALLOWED_IPS` cuando Hermes Agent tenga IP fija.
- No reutilices tokens de Nightscout, Dexcom, Telegram ni JWT de usuarios.

---

## ✨ Capacidades principales

- **Estimación de bolo:** cálculo de apoyo basado en los datos introducidos y el contexto disponible.
- **Autosens y patrones:** análisis de sensibilidad/resistencia y sugerencias basadas en tendencias del historial configurado.
- **Fuentes de glucosa:** integración con Nightscout y fuentes compatibles configuradas en la aplicación.
- **Análisis de comida por IA:** estimación de carbohidratos y macronutrientes a partir de imágenes cuando se configuran proveedores de visión.
- **Pronóstico metabólico:** visualización estimada del impacto de comida/insulina con indicadores de confianza cuando está disponible en el flujo actual.
- **Mapa corporal:** ayuda visual para rotación de sitios de inyección.
- **Modo restaurante:** seguimiento manual de comidas complejas y estimaciones adicionales con revisión humana.
- **Frontend web:** interfaz React/Vite servida junto al backend en los despliegues actuales.

---

## 🚀 Despliegue

### NAS primary

La instancia NAS es la recomendada como **primary**: ejecuta Bolus AI en Docker, mantiene datos locales y expone la aplicación en tu red o dominio doméstico.

Guía completa: [NAS_SETUP.md](./NAS_SETUP.md)

Variables habituales para NAS:

| Grupo | Variables |
| :--- | :--- |
| Base de datos | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL` |
| Persistencia | `DB_DATA_PATH`, `APP_DATA_PATH`, `DATA_DIR` |
| URLs | `NAS_EXTERNAL_URL` o URL local/pública equivalente, `RENDER_EXTERNAL_URL`, `BOT_PUBLIC_URL` |
| Seguridad app | `APP_SECRET_KEY`, `JWT_SECRET` |
| Nightscout | `NIGHTSCOUT_URL`, `NIGHTSCOUT_API_SECRET` |
| Hermes Agent | `AGENT_API_TOKEN`, `AGENT_ALLOWED_IPS` |
| Telegram, si se usa | `ENABLE_TELEGRAM_BOT`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`, `ALLOWED_TELEGRAM_USER_ID` |
| Visión IA, si se usa | `VISION_PROVIDER`, `GOOGLE_API_KEY`, `GEMINI_MODEL`, `GEMINI_MODEL_PRO` |
| Backup, si se usa | `DATABASE_URL_NEON`, `CRON_SCHEDULE` |

### Render backup/emergency

Render se documenta como instancia **backup/emergency**, no como primary. Sirve para contingencia si la instancia NAS no está disponible.

Guía completa: [RENDER_SETUP.md](./RENDER_SETUP.md)

Variables habituales para Render:

| Grupo | Variables |
| :--- | :--- |
| Runtime | `PYTHON_VERSION`, `NODE_VERSION`, `PORT` gestionado por Render |
| Seguridad app | `JWT_SECRET`, `APP_SECRET_KEY` |
| Persistencia | `DATA_DIR=/var/data` y disco persistente de Render |
| Nightscout | `NIGHTSCOUT_URL`, `NIGHTSCOUT_API_SECRET` si aplica |
| Hermes Agent, solo si se habilita en emergencia | `AGENT_API_TOKEN`, `AGENT_ALLOWED_IPS` |
| Visión IA, si se usa | `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `VISION_PROVIDER` |
| Telegram, si se usa | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER` o variable equivalente configurada en tu despliegue |

---

## 📡 Nightscout

Bolus AI puede integrarse con Nightscout según la configuración del usuario. En la arquitectura Hermes ↔ Bolus AI, la **Agent API no expone secretos** y el endpoint de estimación de bolo no registra ni sube tratamientos a Nightscout.

Configura credenciales y permisos de Nightscout solo en el backend de Bolus AI o en la interfaz prevista para ello. No copies secretos de Nightscout a Hermes Agent.

---

## 🧪 Desarrollo local

El backend está construido con FastAPI y el frontend con React/Vite. Para pruebas y desarrollo, revisa los scripts y guías del repositorio antes de activar integraciones externas.

Comprobaciones útiles de documentación:

```bash
python - <<'PY'
from pathlib import Path
import re
for md in Path('.').glob('*.md'):
    for match in re.finditer(r'\[[^\]]+\]\(([^)]+)\)', md.read_text(encoding='utf-8')):
        target = match.group(1).split('#')[0]
        if target and not target.startswith(('http://', 'https://', 'mailto:')):
            print(md, '->', target)
PY
```

---

## ⚖️ Descargo de responsabilidad

Bolus AI es una herramienta de apoyo y documentación técnica para uso personal/controlado. No es un dispositivo médico, no ofrece diagnóstico, no sustituye a profesionales sanitarios y no debe emplearse para administración autónoma de insulina. Verifica siempre todos los datos antes de tomar decisiones terapéuticas.
