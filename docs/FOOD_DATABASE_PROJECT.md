# Proyecto: Base de Datos de Alimentos (Integración)

## Objetivo
Reemplazar el botón redundante de "Alimentos" por una base de datos local y offline que proporcione información de Hidratos de Carbono (HC) e Índice Glucémico (IG).

## Estado Actual: ✅ PROYECTO COMPLETADO (v1.3)
- ✅ **Base de Datos Completa**: 326 alimentos verificados y sin duplicados. 
    - Se ha actualizado la base de datos con **326 alimentos** (incluyendo listas completas de la Fundación Diabetes: Bebidas, Frutos Secos, Platos Preparados).
    - ✅ **Sincronización completada**.

## Hoja de Ruta (Roadmap)
1.  ✅ **Calculadora de Porciones**: Implementado.
2.  ✅ **Favoritos**: Implementado.
3.  ✅ **Integración con Bolus**: Implementado.
4.  ✅ **Fotos / Identificación Visual**: Implementado.
5.  ✅ **Selección Múltiple (Cesta de Alimentos)**: Implementado sistema de carrito con resumen flotante y cálculo total.

## Detalles Técnicos
- **Archivo de datos**: `frontend/src/lib/foodData.json`.
- **Ruta**: `#/food-db`.
- **Versión**: 1.3 (Diciembre 2025).
- **Lógica de Colores (IG)**:
    - Bajo (<55): Verde
    - Medio (55-69): Ámbar
    - Alto (>=70): Rojo
