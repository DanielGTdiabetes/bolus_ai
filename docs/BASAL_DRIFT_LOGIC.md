# Auditoría de Algoritmo Basal: Problema de "Drift" y Solución Híbrida

**Fecha:** 2026-01-08  
**Estado:** Resuelto (Lógica Híbrida Implementada)  
**Severidad Original:** Alta (Predicciones fantasmas de +70 mg/dL)

---

## 1. El Problema Detectado
El usuario reportó una anomalía recurrente en la predicción de glucosa:
- **Escenario:** Glucosa estable (126 mg/dL) + IOB positiva (0.72 U) + COB insignificante (2g).
- **Predicción Errónea:** El sistema proyectaba una subida hasta 201 mg/dL.
- **Causa Raíz:** Lógica de "Basal Drift" basada en promedios históricos.
    - El sistema calculaba el "Promedio de Dosis Basal" de los últimos 7 días (ej. 15 U/día).
    - Comparaba esta referencia con la actividad basal real del momento.
    - Si la dosis del día actual era voluntariamente menor (ej. 12 U/día), el sistema interpretaba la diferencia (-3 U) como un déficit patológico, inyectando glucosa virtual a la predicción.

## 2. La Solución: Modelo Híbrido Basal (Intentional vs Forgotten)

Se ha implementado una nueva lógica en `api/forecast.py` que distingue entre un cambio de dosis intencional y un olvido involuntario.

### A. Modo "Dosis Intencional" (Ventana de 26h)
Si el sistema detecta una inyección de insulina basal (Tresiba, Toujeo, Lantus, etc.) en las **últimas 26 horas**:
1.  Asume que la dosis activa **ES la dosis correcta**.
2.  Establece la `Tasa de Referencia` = `Tasa de Actividad Actual`.
3.  **Resultado:** La diferencia neta es 0. No hay "Drift" (desviación) en la predicción.
    *   *Beneficio:* Permite al usuario reducir su basal por deporte o enfermedad sin que el algoritmo prediga falsas hiperglucemias.

### B. Modo "Olvido / Alerta" (> 26h)
Si **NO** se detecta ninguna inyección en las últimas 26 horas:
1.  El sistema asume un olvido.
2.  Recupera la **Última Dosis Conocida** del historial (ej. la de ayer).
3.  Establece esa dosis antigua como `Referencia`.
4.  Compara con la `Actividad Actual` (que estará cercana a 0 por el olvido).
5.  **Resultado:** Detecta un déficit masivo (ej. -15 U). Predice una subida constante de glucosa.
    *   *Beneficio:* Alerta al usuario de que su glucosa subirá por falta de basal.

## 3. Ejemplo de Comportamiento

| Escenario | Dosis Ayer | Dosis Hoy | Lógica Anterior (7 días) | **Nueva Lógica Híbrida** |
| :--- | :--- | :--- | :--- | :--- |
| **Estándar** | 15 U | 15 U | Estable | **Estable** |
| **Baja por Deporte** | 15 U | **10 U** | Predicción Falsa de Subida (+5U déficit) | **Estable** (Asume 10U como correcto) |
| **Olvido** | 15 U | **0 U** (Olvido) | Predicción de Subida (Correcto) | **Predicción de Subida** (Correcto) |
| **Cambio Horario** | 15 U | 15 U (2h tarde) | Pequeña inestabilidad | **Estable** (Si está dentro de 26h) |

---

## 4. Archivos Afectados
- `backend/app/api/forecast.py`: `get_current_forecast` -> Cálculo de `avg_basal`.

## 5. Próximos Pasos (Opcional)
- Considerar añadir un input manual en "Perfil de Configuración" para definir una "Dosis Basal Teórica" si el usuario desea prescindir de la lógica de "Última Dosis".
- Monitorizar feedback tras 3-4 días de uso continuo.
