# Issue: Falta de Sincronización de Tratamientos desde Nightscout

**Prioridad:** P0 (Crítica)
**Componentes:** `iob.py`, `treatment_retrieval.py`, `api/nightscout.py`

## Descripción
El servicio de cálculo de Insulina Activa (IOB) (`iob.py`) está configurado para leer exclusivamente de la base de datos local (`iob_source = "local_only"`), ignorando cualquier tratamiento que exista en Nightscout pero no en la base de datos local.
Actualmente no existe ningún proceso (Worker, Cron, o Fetch-on-Demand) que descargue tratamientos desde Nightscout hacia la base de datos local.

## Pasos para Reproducir
1. Configurar una instancia de Nightscout con datos de tratamientos recientes (ej. un bolo de 5U hace 30 min).
2. Asegurarse de que la DB local de Bolus AI esté vacía de tratamientos recientes.
3. Abrir Bolus AI o consultar endpoint de IOB.
4. **Resultado Esperado:** IOB ~3-4 U.
5. **Resultado Actual:** IOB 0 U.

## Impacto Clínico
Riesgo alto de **hipoglucemia por stacking de insulina**. La aplicación recomendará dosis completas de corrección ignorando la insulina ya presente en el cuerpo del paciente si esta fue administrada por medios externos.

## Solución Técnica Sugerida
1. Modificar `treatment_retrieval.py` o crear `NightscoutSyncService`.
2. Implementar un método `sync_recent_treatments()` que:
   - Descargue tratamientos de NS de las últimas 24h.
   - Itere y guarde en DB local usando `upsert` (evitando duplicados por ID o timestamp).
   - Se ejecute al inicio de la app y periódicamente (polling) O bajo demanda cuando se solicita un cálculo de bolo.
3. Actualizar `iob.py` para invocar este sync si detecta "stale data" o simplemente confiar en la DB local una vez el sync exista.

## Snippet de Solución (Conceptual)
```python
# En app/services/nightscout_sync.py
async def sync_treatments(user_id: str, lookback_hours=6):
    ns_client = ...
    treatments = await ns_client.get_treatments(hours=lookback_hours)
    for t in treatments:
        await TreatmentRepository.upsert(t)
```
