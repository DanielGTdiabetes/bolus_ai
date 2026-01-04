# Calculadora Manual de Emergencia

## Objetivo
Proporcionar una herramienta "offline-first" dentro de la aplicación que permita calcular bolos incluso si los servidores/API de Nightscout o el backend fallan. Ideal para emergencias o falta de conectividad.

## Implementación
1.  **Nueva Página (Page)**: `ManualCalculatorPage.jsx`
    *   **Inputs**: Glucosa, Hidratos, Ratio (ICR), Sensibilidad (ISF), IOB (Opcional).
    *   **Lógica**: Cálculo puramente matemático en el cliente (Javascript).
    *   **Visual**: Diseño distinguido con tonos rojos de alerta/emergencia.
    *   **Sin Dependencias**: No realiza ninguna llamada a `/api`.

2.  **Enrutamiento**:
    *   Registrada en `bridge.jsx` como `manual`.
    *   Ruta `#/manual` añadida en `main.js`.
    *   Enlace añadido en **Menú > Cuenta y Sistema > Modo Emergencia**.

3.  **Seguridad**:
    *   Se advierte al usuario que es responsabilidad suya introducir los datos correctos ya que no se sincronizan automáticamente.

## Estado
- Implementado y enlazado.
- Listo para usar recargando la aplicación.
