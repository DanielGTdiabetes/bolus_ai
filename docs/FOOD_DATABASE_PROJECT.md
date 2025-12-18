# Proyecto: Base de Datos de Alimentos (Integración)

## Objetivo
Reemplazar el botón redundante de "Alimentos" por una base de datos local y offline que proporcione información de Hidratos de Carbono (HC) e Índice Glucémico (IG).

## Estado Actual: ✅ COMPLETADO
- **Extracción de Datos**: Se han extraído más de 120 alimentos clave de la *Fundación para la Diabetes* y la *CUN*.
- **Información Incluida**:
    - Nombre del alimento.
    - **HC por cada 100g** (calculado a partir de 1 ración = 10g HC).
    - **Índice Glucémico (IG)** con semáforo visual (Alto/Medio/Bajo).
    - **Medida Habitual** (ej. "Unidad", "Vaso", "Plato mediano").
- **Interfaz (FoodDatabasePage.jsx)**:
    - Buscador inteligente.
    - Filtros por categoría (Lácteos, Cereales, Frutas/Verduras, Bebidas, Otros).
    - Diseño premium con tarjetas detalladas.
- **Navegación**: El botón "Alimentos" de la Home ya redirige correctamente a esta nueva sección.

## Detalles Técnicos
- **Archivo de datos**: `frontend/src/lib/foodData.json`.
- **Ruta**: `#/food-db`.
- **Estructura del JSON**:
  ```json
  {
    "version": "1.1",
    "source": "Fundación para la Diabetes / CUN",
    "foods": [
      {
        "category": "...",
        "name": "...",
        "ch_per_100g": 0,
        "ig": 0,
        "measure": "..."
      }
    ]
  }
  ```

## Próximos Pasos Sugeridos
1.  **Calculadora de Porciones**: Permitir al usuario introducir los gramos que va a comer y calcular las raciones automáticamente desde la ficha del alimento.
2.  **Favoritos**: Añadir la posibilidad de marcar alimentos frecuentes.
3.  **Fotos**: Integrar imágenes reales para facilitar la identificación visual.
