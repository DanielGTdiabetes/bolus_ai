# Nightscout Secrets – Transition Plan

## Objetivo
Evitar tokens Nightscout persistidos en `localStorage` y migrarlos a un almacén seguro de backend o, como mínimo, a `sessionStorage` con limpieza en logout.

## Flujo actual (frontend)
1. Si existe `bolusai_ns_config` en `localStorage`, se migra a `sessionStorage` en el arranque.
2. Si el usuario tiene token (`url` + `token`) y sesión autenticada, puede invocar `PUT /api/nightscout/secret` para guardarlo en backend (`migrateNsSecretToBackend`).
3. En logout se purga `sessionStorage` y se elimina la clave legada de `localStorage`.

## Backend
El endpoint `/api/nightscout/secret` persiste `url` y `api_secret` por usuario (tabla `nightscout_secrets`). El frontend sólo debería guardar en memoria de sesión; el backend es la fuente de verdad.

## Recomendaciones operativas
- Habilitar `ALLOW_UNAUTH_NUTRITION_INGEST=false` en producción para evitar ingestas anónimas.
- Rotar tokens antiguos tras la migración.
- Supervisar logs de advertencia `NS config migration failed` para detectar navegadores que bloqueen `sessionStorage`.
