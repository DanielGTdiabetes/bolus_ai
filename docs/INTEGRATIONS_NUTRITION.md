# Ingesta de nutrición (Health Auto Export / MyFitnessPal)

## Autenticación
- Opción estándar: `Authorization: Bearer <token>` (JWT del usuario).
- Modo puente (sin headers complejos): añadir `?key=<NUTRITION_INGEST_SECRET>` o el header opcional `X-Ingest-Key: <valor>`.
- Configura el secreto en el backend con la variable de entorno `NUTRITION_INGEST_SECRET` (se mantiene compatibilidad con `NUTRITION_INGEST_KEY`).
- Los accesos con clave se registran (éxitos y rechazos) sin exponer el valor.

Ejemplo listo para el atajo del puente:
```
https://bolus-ai-1.onrender.com/api/integrations/nutrition?key=TU_SECRETO
```

## Comandos de verificación rápida

```bash
# 1) Ingesta con clave (sin JWT)
curl -X POST "https://bolus-ai-1.onrender.com/api/integrations/nutrition?key=TU_SECRETO" \
  -H "Content-Type: application/json" \
  -d '{"carbs":20,"fat":5,"protein":7,"fiber":12,"date":"'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'"}'

# 2) Rechazo sin clave ni JWT
curl -X POST "https://bolus-ai-1.onrender.com/api/integrations/nutrition" \
  -H "Content-Type: application/json" \
  -d '{"carbs":10,"date":"'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'"}'
```

## Notas de deduplicación
- Dos eventos con mismo timestamp y macros pero fibra distinta se actualizan (no se descartan).
- Eventos con fibra ≥ 1 g se guardan aunque los demás macros sean 0.
