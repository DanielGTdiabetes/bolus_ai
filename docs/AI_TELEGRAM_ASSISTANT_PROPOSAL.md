# Propuesta: Asistente IA Proactivo (Telegram Bot)

## 1. Visión General
Transformar la aplicación de una simple "calculadora de bolos" a un **Asistente personal proactivo**. El objetivo es reducir la fricción en la gestión diaria de la diabetes, eliminando pasos manuales y anticipándose a problemas mediante avisos inteligentes.

El sistema no "toma el control" (no modifica rangos ni tratamientos automáticamente), sino que actúa como un copiloto que **sugiere y facilita**.

## 2. Principio de Seguridad: Separación de Responsabilidades
Para mantener la seguridad médica y la precisión, establecemos una **línea roja** clara:

*   **La App (Motor Matemático)**: Es la única autoridad para los cálculos. Contiene la lógica determinista (`curves.py`, `isf.py`) que ya ha sido validada.
    *   *Responsabilidad*: Calcular bolos, determinar IOB, ajustar ISF.
*   **La IA (El Asistente)**: Actúa como **interfaz** y **orquestador**.
    *   *Responsabilidad*: Detectar el evento, limpiar los datos de entrada y **consultar** al motor matemático.
    *   **REGLA DE ORO**: La IA nunca "inventa" ni recalcula una dosis. Si necesita un valor, invoca a la función de la App.
    *   *Ejemplo*: La IA no calcula `60g / 10 ratio = 6u`. La IA llama a `calculate_bolus(carbs=60)` y la App devuelve `6u`.

### C. Catálogo de Funciones Expuestas (Cobertura Total)
El objetivo es que **cualquier cosa** que puedas hacer clicando en la web, puedas hacerla pidiéndosela al Bot. La IA tendrá "herramientas" (function calling) para:
1.  **Calculadoras**: Bolus Estándar, Bolus Extendido, Corrección, Basal Retrasada.
2.  **Simuladores**: "¿Qué pasaría si como 50g ahora?" (Llama al motor de curvas de predicción).
3.  **Base de Datos**: Búsqueda de alimentos y conteo de hidratos.
4.  **Análisis**: Generación de reportes (`get_nightscout_stats`) o diagnósticos (`iob_analysis`).
5.  **Configuración**: Ajustes temporales de perfil (ej. "Activa modo deporte").
6.  **Visión**: Procesamiento de imágenes (platos o etiquetas) para extracción automática de carbohidratos.
7.  **Auditoría**: Acceso al motor de sugerencias (`suggestion_engine`) para proponer cambios en ratios o sensibilidad basados en historial. [COMPLETADO ✅]

## 3. Componentes Clave

### A. Canal de Comunicación: Telegram Bot
Se elige Telegram por su eficiencia y bajo consumo de recursos.
*   **Ventajas**:
    *   Funciona bien con **redes lentas**.
    *   Interfaz tipo chat familiar.
    *   Notificaciones "Push" nativas.
    *   Botones de acción rápida (Callback buttons) para confirmar acciones con un solo clic.
    *   **Notas de Voz**: Capacidad de hablarle al Bot ("Me como un plátano") y que transcriba y procese el audio automáticamente.

### B. El "Vigilante" (The Watcher)
Un servicio en el backend (`proactive.py`) que monitoriza dos fuentes de información:
1.  **Entradas de Datos Externos**: Detecta cuando llega un archivo (ej. `json` de MyFitnessPal) o una sincronización de salud.
2.  **Estado de Glucosa (Nightscout)**: Monitoriza tendencias en tiempo real, no solo valores absolutos.

### C. Control Total (Interruptor Maestro) [NUEVO ✅]
Se ha implementado un interruptor de seguridad en el panel de Ajustes de la Web App. Permite desactivar completamente ("Kill Switch") toda la lógica del bot (respuestas y trabajos en segundo plano) instantáneamente en caso de duda o mantenimiento.

## 3. Casos de Uso (Flujos Implementados)

### Caso 1: Automatización de Comidas (MyFitnessPal) [COMPLETADO ✅]
1.  **Detección**: El usuario registra la comida en MFP. El backend detecta la entrada de datos.
2.  **Procesamiento IA**: La IA limpia los datos y consulta la calculadora determinista.
3.  **Interacción**: El Bot envía un mensaje con botones de acción rápida.
4.  **Acción**: Registro automático tras confirmación.

### Caso 2: Asesoramiento Proactivo (Pre-comida) [COMPLETADO ✅]
1.  **Contexto**: Monitoriza la glucosa 40-60 min antes de las comidas habituales.
2.  **Análisis**: Si detecta hiperglucemia incipiente antes de comer.
3.  **Mensaje**: *"Son las 13:30. Estás en 160mg/dL. Sería ideal corregir ahora."*

### Caso 3: Alerta de Tendencia (Proactivo) [COMPLETADO ✅]
*   Detecta subida/bajada rápida (Slope > 2.0 mg/dL/min) sin bolus reciente activo.
*   **Gating Inteligente**: No molesta si acabas de comer (filtro de 3h) o poner insulina.

### Caso 4: Monitorización de Bolo Doble (Combo/Extendido) [COMPLETADO ✅]
Gestionar los recordatorios de la segunda parte de un bolo extendido.
*   **Inteligencia**: Verifica si la glucosa está bajando peligrosamente antes de sugerir poner la 2ª dosis restante.
*   **Acción**: Permite confirmar la dosis o posponerla con un clic.

### Caso 5: Gestión Inteligente de Basal (Lenta) [COMPLETADO ✅]
Evitar olvidos o dosis dobles.
1.  **Recordatorio**: A la hora configurada (ej. 22:00).
2.  **Seguridad (Anti-Race Condition)**: Verifica justo antes de grabar si ya existe una entrada reciente en la BD.
3.  **Cálculo de Retraso**: Si respondes tarde, ajusta la dosis proporcionalmente (lógica de `basal_engine`).

### Caso 6: Interacción Multimodal (Visión/Gemini) [COMPLETADO ✅]
1.  **Acción**: Foto del plato al chat.
2.  **Proceso**: Gemini Flash analiza los alimentos y estima carbohidratos.
3.  **Resultado**: Botón **"💉 Calcular para X g"** que abre directamente la calculadora con los datos pre-cargados.

### Caso 7: Asistencia de Microbolos (Gestión de Curva Fina) [COMPLETADO ✅]
Actuar como un "Lazo Cerrado Asistido".
1.  **Escenario**: Subida lenta persistente (pendiente suave pero constante).
2.  **Sugerencia**: Sugiere un micro-bolo conservador (pasos de 0.5u, máximo 1.0u) para aplanar la curva.
3.  **Seguridad**: Factor de corrección reducido (40% de lo necesario) para evitar sobre-corrección.

### Caso 8: Resumen Matutino (Feedback Diario) [COMPLETADO ✅]
Reporte diario a las 08:00 AM (o configurable) con:
*   Estadísticas de la noche (media, variación).
*   Eventos destacados (hipos/hipers).

### Caso 9: Auditoría y Optimización (Bajo Demanda) [COMPLETADO ✅]
1.  **Acción**: El usuario solicita "Analiza mis datos" o "¿Cómo van mis ratios?".
2.  **Proceso**: La IA invoca al `suggestion_engine` (Tool: `get_optimization_suggestions`) que revisa los últimos 7 días.
3.  **Resultado**: Ofrece sugerencias concretas si detecta patrones claros (ej. "En el desayuno te quedas corto el 60% de las veces → Sugiero revisar ICR").

## 4. Fase 2: El Asesor en la Sombra (Futuro V2)
*(Anteriormente "Aprendizaje de Horarios")*

Se ha decidido **posponer** el módulo de auto-aprendizaje (Machine Learning / Auto-Tune) a una segunda fase por motivos de seguridad y madurez de datos:

1.  **Filosofía de auditoría pasiva**: El sistema no debe modificar parámetros (ICR/ISF/Horarios) por sí solo. Debe aprender de forma pasiva y **sugerir** cambios solo cuando tenga una certeza estadística alta.
2.  **Necesidad de Datos**: Los algoritmos de clustering requieren al menos 4-8 semanas de historial limpio y consistente en el nuevo sistema (`DataStore`) para ofrecer conclusiones válidas.
3.  **Estrategia V2**: Una vez recolectados los datos con la V1 actual, se implementará un proceso analítico (semanal/mensual) que generará un informe de "Sugerencias de Optimización" para que el usuario las apruebe manualmente.

## 5. Consideraciones Técnicas y Limitaciones de Red

Dado que la conectividad puede ser inestable:
1.  **Comunicación Ligera**: Los mensajes de texto de Telegram consumen muy pocos datos.
2.  **Gestión de "Timeout"**: Si el backend intenta contactar a Telegram y falla (sin red), debe tener una cola de reintento inteligente (no bombardear cuando vuelva la red, solo enviar el último estado relevante).
3.  **Fallbacks**: Si el asistente no responde, la App principal (local) siempre debe funcionar como respaldo manual completo.
4.  **Seguridad**: El Bot solo responderá al ID de usuario específico (whitelisting) para evitar accesos no autorizados.



## 6. Filosofía del Asistente: "El Compañero Transparente"

