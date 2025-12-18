# Proyecto: Base de Datos de Alimentos (Integración)

## Objetivo
Reemplazar el botón redundante de "Alimentos" por una base de datos local y offline que proporcione información de Hidratos de Carbono (HC) e Índice Glucémico (IG).

## Estado Actual: ✅ COMPLETADO (Fase 2 - UI) | 🚧 EN PROCESO (Fase 2 - Datos)
- ✅ **Interfaz Premium**: Implementada con banner, iconos por categoría y tarjetas adaptativas.
- ✅ **Funcionalidades Core**: Calculadora de raciones, Sistema de favoritos y Envío a Bolus funcionando.
- 🚧 **Sincronización de Datos**: 
    - Se ha realizado la auditoría de la web original. 
    - Tenemos **215 alimentos** locales vs **319 alimentos** en la web.
    - Los ~100 alimentos faltantes (Bebidas, Otros, Frutos Secos) ya han sido extraídos pero **están pendientes de guardarse en `foodData.json`** en la próxima sesión para evitar pérdida de datos durante la pausa.

## Hoja de Ruta (Roadmap)
1.  ✅ **Calculadora de Porciones**: Implementado.
2.  ✅ **Favoritos**: Implementado.
3.  ✅ **Integración con Bolus**: Implementado.
4.  ✅ **Fotos / Identificación Visual**: Implementado.
5.  [ ] **Selección Múltiple (Cesta de Alimentos)**: Implementar un sistema de "carrito" para añadir varios alimentos y enviar la suma total de HC al cálculo de bolo (ej. Patatas + Queso).

## Detalles Técnicos
- **Archivo de datos**: `frontend/src/lib/foodData.json`.
- **Ruta**: `#/food-db`.
- **Versión**: 1.2 (Diciembre 2025).
- **Lógica de Colores (IG)**:
    - Bajo (<55): Verde
    - Medio (55-69): Ámbar
    - Alto (>=70): Rojo
