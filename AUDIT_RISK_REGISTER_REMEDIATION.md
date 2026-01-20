# Risk Register - Remediation Status

| id | riesgo | severidad | probabilidad | impacto | detección | mitigación | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R-01 | Doble registro del endpoint /vision/estimate | Alta | Media | Fallos en router/OpenAPI | Revisar logs y /docs | Eliminar decorador duplicado. | **[RESUELTO]** |
| R-02 | Excepciones silenciadas en notificaciones | Alta | Media | Alertas fallidas sin diagnóstico | Revisar logs (ausencia de stacktrace) | Loggear exc_info y métricas de fallos. | **[RESUELTO] (Logging)** |
| R-03 | Excepciones silenciadas en bot (Warsaw check) | Media | Media | Comportamiento inconsistente en proactivos | QA con datos corruptos | Loggear error y añadir alerta. | **[RESUELTO] (Logging)** |
| R-04 | TZ naive en dedupe de nutrición | Alta | Media | Duplicados o pérdida de ingestas | Comparar ingestión multi-TZ | Normalizar timestamps a UTC aware. | **[ACEPTADO] (Evitar migración DB)** |
| R-05 | Modelo NightscoutSecrets usa DateTime naive | Media | Baja | Filtros inconsistentes con otros modelos | Revisión de consultas por fecha | Migrar a timezone=True. | **[ACEPTADO] (Evitar migración DB)** |
| R-06 | Endpoints de bot sin auth | Media | Alta | Exposición de capacidades y job state | Revisar acceso sin token | Requerir auth/admin. | **[RESUELTO]** |
| R-07 | Health/jobs sin auth | Media | Alta | Recon sobre estado y uptime | Revisión en staging | Proteger con auth o limitar info. | **[RESUELTO]** |
| R-08 | Middleware devuelve detalle de excepción | Media | Media | Info leak en 500s | Tests forzando error | Devolver mensaje genérico. | **[RESUELTO]** |
| R-09 | Jobs declarados sin schedule | Baja | Alta | Funcionalidades inactivas | Comparar registry vs scheduler | Programar o eliminar jobs. | **[RESUELTO]** |
| R-10 | Rutas SPA sin loader (labs/restaurant) | Baja | Alta | Pantallas rotas | QA de navegación | Condicionar rutas o crear páginas. | **[RESUELTO]** |
