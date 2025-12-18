# Proyecto: Base de Datos de Alimentos (Integración)

## Objetivo
Reemplazar el botón redundante de "Alimentos" por una base de datos local y offline que proporcione información de Hidratos de Carbono (HC) e Índice Glucémico (IG).

## Estado Actual: ✅ COMPLETADO (Fase 2)
- ✅ **Extracción de Datos (v1.2)**: Consolidación de **215 alimentos**.
- ✅ **Categoría de Proteínas**: Inclusión de alimentos con 0 HC.
- ✅ **Calculadora de Porciones**: Implementada en cada tarjeta de alimento.
- ✅ **Sistema de Favoritos**: Guardado persistente y filtro rápido.
- ✅ **Integración con Bolus**: Envío directo de datos al calculador de bolo.
- ✅ **Identificación Visual**: Iconos por categoría y banner premium.

## Hoja de Ruta (Roadmap)
1.  ✅ **Calculadora de Porciones**: Implementado.
2.  ✅ **Favoritos**: Implementado.
3.  ✅ **Integración con Bolus**: Implementado.
4.  ✅ **Fotos / Identificación Visual**: Implementado.

## Detalles Técnicos
- **Archivo de datos**: `frontend/src/lib/foodData.json`.
- **Ruta**: `#/food-db`.
- **Versión**: 1.2 (Diciembre 2025).
- **Lógica de Colores (IG)**:
    - Bajo (<55): Verde
    - Medio (55-69): Ámbar
    - Alto (>=70): Rojo
