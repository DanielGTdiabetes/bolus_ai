# API interna para agentes locales

## Propósito

La API interna `/api/agent/*` permite que un agente externo local, por ejemplo Hermes Agent en un mini PC dentro de la red doméstica, consulte el estado de Bolus AI y solicite estimaciones de bolo de forma controlada.

Esta API está diseñada para integración **read-only / estimate-only**:

- Puede consultar estado, glucosa actual y contexto resumido.
- Puede pedir una estimación de bolo reutilizando el motor actual de Bolus AI.
- No administra insulina.
- No decide automáticamente tratamientos.
- No guarda tratamientos.
- No sube tratamientos a Nightscout.
- No expone tokens ni secretos de Nightscout/Dexcom.

> Advertencia médica: Bolus AI y esta API son herramientas de apoyo a la decisión. Cualquier recomendación o estimación debe ser revisada por la persona usuaria/cuidadora. No debe usarse para administración automática de insulina ni para sustituir criterio clínico profesional.

## Seguridad

La API está cerrada por defecto. Para activarla se requiere configurar un token interno:

```env
AGENT_API_TOKEN=valor_largo_aleatorio
```

Cada petición debe enviar:

```http
Authorization: Bearer <AGENT_API_TOKEN>
```

Si `AGENT_API_TOKEN` no está configurado o está vacío, todos los endpoints `/api/agent/*` devuelven `503` y quedan bloqueados de forma segura.

Opcionalmente se puede restringir por IP:

```env
AGENT_ALLOWED_IPS=192.168.1.50,127.0.0.1
```

Si `AGENT_ALLOWED_IPS` está vacío, solo se exige el token. Si está configurado, la IP cliente debe estar en la lista y además presentar el token correcto.

## Variables de entorno

| Variable | Obligatoria | Descripción |
| --- | --- | --- |
| `AGENT_API_TOKEN` | Sí, para habilitar la API | Token bearer interno. Debe ser largo, aleatorio y secreto. |
| `AGENT_ALLOWED_IPS` | No | Lista separada por comas de IPs autorizadas. |

No añadas valores reales al repositorio, logs, tickets o capturas.

## Endpoints

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

Devuelve contexto resumido útil para un agente conversacional o de automatización local.

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

### `POST /api/agent/bolus/estimate`

Solicita una estimación de bolo reutilizando el cálculo existente de Bolus AI.

Garantías de seguridad de este endpoint:

- no llama a `log_treatment`;
- no guarda tratamientos;
- no sube tratamientos a Nightscout;
- no cambia la lógica clínica del cálculo existente;
- desactiva la persistencia de ejecuciones auxiliares de autosens para mantener la estimación sin escritura de datos.

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

## Ejemplo de uso desde Hermes Agent

Configuración conceptual del agente local:

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

Flujo recomendado:

1. Hermes llama a `/api/agent/status`.
2. Si la API está activa, llama a `/api/agent/context`.
3. Si el usuario pide una estimación, Hermes llama a `/api/agent/bolus/estimate` con los datos indicados por el usuario.
4. Hermes muestra la estimación y advertencias.
5. La persona usuaria decide manualmente. Hermes no administra insulina ni registra tratamientos automáticamente.

## Límites y decisiones de diseño

- La API vive en un router aislado (`app/api/agent.py`).
- La autenticación de esta API no reutiliza JWT de usuario; usa un token interno específico.
- La API no está abierta por defecto.
- La estimación de bolo reutiliza `calculate_bolus_stateless_service`.
- No se crea un `bolus_core` nuevo ni se duplica la lógica clínica.
- El usuario operativo interno actual es `admin`, coherente con despliegues NAS/locales existentes.
- Los cambios son reversibles: retirar el include del router y eliminar `app/api/agent.py` desactiva la integración.
