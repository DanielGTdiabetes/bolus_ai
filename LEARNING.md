# Aprendizaje de absorción (timing)

## Qué datos se guardan
- **meal_experiences**: experiencias por tratamiento (meal_type, macros, carb_profile, event_kind, window_status, outcomes de BG 2h/3h/5h, score y datos de calidad).  
- **meal_clusters**: clusters por combinación de macros + carb_profile + tags_key con centroides, curva sugerida (duración, pico, cola), n_ok, confianza y timestamps.

Todos los datos viven **exclusivamente** en PostgreSQL; no se usan ficheros ni caches en memoria para decisiones de aprendizaje.

## Cuándo un evento es OK / descartado / excluido
- **OK**: hay datos suficientes en la ventana requerida y no hay interferencias (snacks/bolos extra).
- **Descartado**: hay interferencias dentro de la ventana (snacks > 5g o correcciones > 0.5u).
- **Excluido**: eventos no aptos para aprendizaje (correction-only, carbs-only) o datos insuficientes en la ventana requerida.

## Cuándo entra en uso una curva aprendida
Una curva aprendida se aplica en forecast/alertas **solo** cuando:
- El cluster tiene `n_ok >= 5`, y
- La confianza es `medium` o `high`.

Si no se cumple lo anterior, se usa la curva base del perfil de carbohidratos.

## Cómo verificar que el aprendizaje está activo

### SQL (Postgres)
```
SELECT count(*) FROM meal_experiences;
SELECT count(*) FROM meal_clusters;
SELECT event_kind, count(*) FROM meal_experiences GROUP BY event_kind;
```

### API
- `GET /api/learning/summary`  
  Debe devolver:
  - `total_events`
  - `ok_events`
  - `discarded_events`
  - `excluded_events`
  - `clusters_active`

- `GET /api/learning/clusters`  
  Debe devolver una lista vacía si aún no hay suficientes eventos OK, sin error.

## Cómo desactivar temporalmente el uso de curvas aprendidas
En la configuración de usuario (`learning.absorption_learning_enabled = false`) se puede desactivar el uso de curvas aprendidas.  
En ese modo, el forecast vuelve a usar únicamente la curva base por `carb_profile`.
