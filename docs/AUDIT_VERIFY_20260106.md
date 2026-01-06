## Auditoría T1D – Verificación inicial (2026-01-06)

Hallazgos y estado de reproducción antes de cambios:

1. **Simulación de bolo ignora IOB/COB/tendencia al editar dosis** – repro.
2. **IOB unavailable se fuerza a 0 y se calcula igual** – repro.
3. **Webhook nutrición ignora fiber y no actualiza solo-fiber** – repro.
4. **COB mostrado usa modelo lineal 4h sin macros** – repro.
5. **Token Nightscout en localStorage** – repro.
6. **Home muestra predicción stale cuando falla forecast/current** – repro.
7. **Webhook nutrición acepta ingest sin auth por defecto** – repro.

## Estado post-cambios
- Mitigaciones implementadas en backend/frontend para todos los hallazgos enumerados arriba (confirmación requerida, simulación con contexto, fibra, COB model flag, storage seguro y auth).
