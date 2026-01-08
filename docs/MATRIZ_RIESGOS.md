# Matriz de Riesgos y Hallazgos T1D

| ID | Hallazgo | Probabilidad | Severidad | Detectabilidad | Prioridad | Mitigación Propuesta |
|----|----------|--------------|-----------|----------------|-----------|----------------------|
| **R-01** | **Ceguera IOB Externo** | Alta | Crítica | Baja (Silencioso) | **P0** | Implementar `fetch_treatments_from_nightscout` en el cálculo de IOB o un Sync Worker de fondo. |
| **R-02** | Stacking en Correcciones | Media | Alta | Media | **P1** | Bloquear correcciones si IOB es "Unknown" o "Stale" (>1h sin datos). |
| **R-03** | Fibra perdida en Import | Media | Media | Alta (Usuario lo ve) | **P2** | Relajar filtros de deduplicación en `integrations.py` para permitir updates de solo-fibra. |
| **R-04** | Predicción alarmista (Drop) | Alta | Baja (Susto) | Inmediata | **P2** | Mostrar curva "Fantasmal" (Baseline) siempre junto a la predicción simulada. |
| **R-05** | Redondeo 0.5U en Hipo | Baja | Media | Alta | **P3** | En `_smart_round`, forzar `floor` si BG < 100 o tendencia bajista fuerte, ignorar "Techne Rounding". |
| **R-06** | Token Nightscout en Logs | Baja | Alta | Difícil | **P1** | Auditar `nightscout.py` y asegurar que `ns.api_secret` nunca se imprima en `logger.info`. |
| **R-07** | Timezone Mismatch en Import | Alta | Media | Media | **P2** | Forzar UTC en `integrations.py` y convertir a Local solo para display. Standardizar `created_at` en DB como UTC naive o aware pero consistente. |

## Definiciones
- **Probabilidad:** Frecuencia con la que un usuario T1D real encontraría esto (Alta = Diario).
- **Severidad:** Daño potencial (Crítica = Hospital/Hipo severa, Baja = Confusión UI).
- **Detectabilidad:** Facilidad para que el usuario note que algo va mal antes de inyectarse.
