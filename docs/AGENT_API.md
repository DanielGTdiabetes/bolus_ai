# Hermes Agent Integration / Agent API

La API interna `/api/agent/*` permite que **Hermes Agent** u otro agente local autorizado consulte Bolus AI y solicite estimaciones de bolo de forma controlada.

La integración mantiene una frontera clara:

```text
Hermes Agent
    ↓
/api/agent/* con Bearer token
    ↓
Bolus AI core
```

- **Bolus AI** es el motor clínico central.
- **Hermes Agent** es una capa conversacional/orquestadora.
- Hermes no es el motor médico y no debe presentarse como tal.
- La API es **read-only / estimate-only / human-in-the-loop**.

> **Advertencia médica:** Bolus AI y esta API no son un dispositivo médico. No administran insulina, no deben automatizar administración de insulina y no sustituyen criterio clínico profesional. Toda estimación debe ser revisada por la persona usuaria/cuidadora.

---

## Alcance permitido

La Agent API puede:

- Consultar estado de la aplicación.
- Consultar glucosa actual desde la fuente configurada.
- Consultar contexto resumido.
- Consultar un perfil clínico no identificable con valores por defecto de ejemplo.
- Solicitar una estimación de bolo reutilizando el motor existente de Bolus AI.

La Agent API no puede:

- Administrar insulina.
- Decidir tratamientos automáticamente.
- Guardar tratamientos.
- Subir tratamientos a Nightscout.
- Exponer tokens o secretos de Nightscout/Dexcom.
- Modificar ratios, perfiles o ajustes de usuario.

---

## Seguridad

La API está cerrada por defecto. Para activarla se requiere configurar un token interno:

```env
AGENT_API_TOKEN=valor_largo_aleatorio
```

Cada petición debe enviar:

```http
Authorization: Bearer <AGENT_API_TOKEN>
```

Si `AGENT_API_TOKEN` no está configurado o está vacío, los endpoints `/api/agent/*` devuelven `503` y quedan bloqueados de forma segura.

Opcionalmente se puede restringir por IP:

```env
AGENT_ALLOWED_IPS=192.168.1.50,127.0.0.1
```

Si `AGENT_ALLOWED_IPS` está vacío, solo se exige el token. Si está configurado, la IP cliente debe estar en la lista y además presentar el token correcto.

### Variables de entorno

| Variable | Obligatoria | Descripción |
| :--- | :--- | :--- |
| `AGENT_API_TOKEN` | Sí, para habilitar la API | Token bearer interno. Debe ser largo, aleatorio y secreto. |
| `AGENT_ALLOWED_IPS` | No | Lista separada por comas de IPs autorizadas. Útil para limitar acceso al host de Hermes Agent. |

No añadas valores reales al repositorio, logs, tickets o capturas.

---

## Flujo recomendado con Hermes Agent

```text
1. Hermes llama a GET /api/agent/status.
2. Si la API está activa, Hermes llama a GET /api/agent/context.
3. Si necesita parámetros clínicos base para explicar una estimación, Hermes llama a GET /api/agent/profile.
4. Si el usuario pide una estimación, Hermes recopila datos y llama a POST /api/agent/bolus/estimate.
5. Bolus AI devuelve la estimación, warnings y metadatos.
6. Hermes muestra el resultado sin registrar tratamiento.
7. La persona usuaria/cuidadora decide manualmente.
```

---

## Endpoints actuales

### `GET /api/agent/status`

Devuelve estado básico de la aplicación para un agente local.

Incluye:

- versión de la app;
- entorno;
- timestamp UTC;
- modo seguro;
- si la API de agente está activa;
- estado resumido de Nightscout;
- estado resumido de Dexcom.

No fuerza llamadas externas a Nightscout/Dexcom, para que el endpoint pueda usarse como healthcheck interno sin depender de servicios externos.

Ejemplo:

```bash
curl -s \
  -H "Authorization: Bearer ${AGENT_API_TOKEN}" \
  http://bolus-ai.local:8000/api/agent/status
```

### `GET /api/agent/glucose/current`

Devuelve glucosa actual desde la fuente configurada actualmente. La unidad se normaliza a `mg/dL`.

Campos principales:

- `glucose_mgdl`;
- `trend`;
- `timestamp`;
- `source`;
- `unit` (`mg/dL`);
- `age_minutes`;
- `stale`;
- `warnings`.

Ejemplo:

```bash
curl -s \
  -H "Authorization: Bearer ${AGENT_API_TOKEN}" \
  http://bolus-ai.local:8000/api/agent/glucose/current
```

### `GET /api/agent/context`

Devuelve contexto resumido útil para un agente conversacional.

Incluye:

- glucosa actual;
- tendencia;
- IOB si está disponible;
- COB si está disponible;
- estado de Nightscout;
- avisos relevantes.

No devuelve credenciales, tokens ni secretos.

Ejemplo:

```bash
curl -s \
  -H "Authorization: Bearer ${AGENT_API_TOKEN}" \
  http://bolus-ai.local:8000/api/agent/context
```

### `GET /api/agent/profile`

Devuelve una plantilla de perfil clínico **solo lectura** con valores por defecto no identificables. No lee ni expone valores reales de usuario, no calcula dosis, no persiste datos y no modifica estado.

Campos devueltos:

- `dia_hours`: duración de acción de insulina en horas;
- `isf_mgdl_per_u`: factor de sensibilidad en mg/dL por unidad;
- `icr_g_per_u`: ratio insulina-carbohidratos en gramos por unidad;
- `basal_u_per_h`: tasa basal de referencia en unidades por hora;
- `target_low_mgdl`: límite inferior del rango objetivo en mg/dL;
- `target_high_mgdl`: límite superior del rango objetivo en mg/dL;
- `insulin_onset_min`: inicio aproximado de acción de insulina en minutos;
- `insulin_peak_min`: pico aproximado de acción de insulina en minutos.

Respuesta actual de ejemplo:

```json
{
  "dia_hours": 4,
  "isf_mgdl_per_u": 78,
  "icr_g_per_u": 10,
  "basal_u_per_h": 0.625,
  "target_low_mgdl": 90,
  "target_high_mgdl": 160,
  "insulin_onset_min": 15,
  "insulin_peak_min": 75
}
```

Ejemplo:

```bash
curl -s \
  -H "Authorization: Bearer ${AGENT_API_TOKEN}" \
  http://bolus-ai.local:8000/api/agent/profile
```

Seguridad:

- requiere `Authorization: Bearer <AGENT_API_TOKEN>` igual que el resto de `/api/agent/*`;
- devuelve `401` si falta el bearer token;
- devuelve `503` si `AGENT_API_TOKEN` no está configurado;
- no debe sustituir una revisión clínica ni usarse para automatizar administración de insulina.

Riesgos y advertencias:

- aunque los valores son de ejemplo, pueden parecer parámetros terapéuticos; el agente debe etiquetarlos como plantilla no personalizada;
- si en el futuro se conectan valores reales de usuario, habrá que revisar consentimiento, mínimos datos expuestos, auditoría y controles de acceso;
- no usar este endpoint para ejecutar cambios de bomba, pluma o Nightscout.

### `POST /api/agent/bolus/estimate`

Solicita una estimación de bolo reutilizando el cálculo existente de Bolus AI.

Garantías de seguridad de este endpoint:

- no llama a `log_treatment`;
- no guarda tratamientos;
- no sube tratamientos a Nightscout;
- no cambia la lógica clínica del cálculo existente;
- desactiva la persistencia de ejecuciones auxiliares de autosens;
- no actualiza ni crea la caché global de IOB (`iob_cache.json`) para mantener la estimación sin escritura de datos.

Ejemplo mínimo con glucosa manual:

```bash
curl -s \
  -X POST \
  -H "Authorization: Bearer ${AGENT_API_TOKEN}" \
  -H "Content-Type: application/json" \
  http://bolus-ai.local:8000/api/agent/bolus/estimate \
  -d '{
    "carbs_g": 45,
    "bg_mgdl": 145,
    "meal_slot": "lunch",
    "cr_g_per_u": 10,
    "isf_mgdl_per_u": 50,
    "target_mgdl": 100,
    "confirm_iob_unknown": true,
    "manual_iob_u": 0
  }'
```

Respuesta resumida:

- `estimation`: respuesta completa del motor existente;
- `explanation`: explicación textual;
- `warnings`: advertencias;
- `confidence`: `null` si no existe en el motor actual;
- `forecast_curve`: `null` si no existe en el flujo actual;
- `persisted`: siempre `false`;
- `nightscout_uploaded`: siempre `false`.

---

## Ejemplo de configuración conceptual en Hermes Agent

```yaml
bolus_ai:
  base_url: "http://bolus-ai.local:8000"
  token_env: "AGENT_API_TOKEN"
  mode: "consult_only"
  allowed_actions:
    - "get_status"
    - "get_current_glucose"
    - "get_context"
    - "estimate_bolus"
  forbidden_actions:
    - "administer_insulin"
    - "save_treatment"
    - "upload_nightscout_treatment"
    - "change_user_settings"
```

---

## Despliegue NAS vs Render

| Entorno | Rol recomendado | Uso de Agent API |
| :--- | :--- | :--- |
| NAS | Primary local | Opción recomendada para Hermes Agent dentro de la red doméstica. |
| Render | Backup/emergency | Solo habilitar si se necesita contingencia y se protegen token, IPs y acceso público. |

Para NAS, configura `AGENT_API_TOKEN` en el entorno del backend y, si Hermes tiene IP fija, añade `AGENT_ALLOWED_IPS`.

Para Render, recuerda que la URL suele ser pública. Si se habilita la Agent API en Render, usa un token distinto del NAS y restringe acceso por IP cuando sea posible.

---

## Límites y decisiones de diseño

- La API vive en un router aislado (`app/api/agent.py`).
- La autenticación de esta API no reutiliza JWT de usuario; usa un token interno específico.
- La API no está abierta por defecto.
- La estimación de bolo reutiliza `calculate_bolus_stateless_service`.
- No se crea un `bolus_core` nuevo ni se duplica la lógica clínica.
- El usuario operativo interno actual es `admin`, coherente con despliegues NAS/locales existentes.
- Los cambios son reversibles: retirar el include del router y eliminar `app/api/agent.py` desactiva la integración.
