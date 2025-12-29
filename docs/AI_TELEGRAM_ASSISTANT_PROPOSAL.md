# Propuesta: Asistente IA Proactivo (Telegram Bot)

## 1. Visión General
Transformar la aplicación de una simple "calculadora de bolos" a un **Asistente personal proactivo**. El objetivo es reducir la fricción en la gestión diaria de la diabetes, eliminando pasos manuales y anticipándose a problemas mediante avisos inteligentes.

El sistema no "toma el control" (no modifica rangos ni tratamientos automáticamente), sino que actúa como un copiloto que **sugiere y facilita**.

## 2. Componentes Clave

### A. Canal de Comunicación: Telegram Bot
Se elige Telegram por su eficiencia y bajo consumo de recursos.
*   **Ventajas**:
    *   Funciona bien con **redes lentas**.
    *   Interfaz tipo chat familiar.
    *   Notificaciones "Push" nativas.
    *   Botones de acción rápida (Callback buttons) para confirmar acciones con un solo clic.

### B. El "Vigilante" (The Watcher)
Un servicio en el backend que monitoriza dos fuentes de información:
1.  **Entradas de Datos Externos**: Detecta cuando llega un archivo (ej. `json` de MyFitnessPal) o una sincronización de salud.
2.  **Estado de Glucosa (Nightscout)**: Monitoriza tendencias en tiempo real, no solo valores absolutos.

## 3. Casos de Uso (Flujos)

### Caso 1: Automatización de Comidas (MyFitnessPal)
1.  **Detección**: El usuario registra la comida en MFP. El backend detecta la entrada de datos.
2.  **Procesamiento IA**: La IA limpia los datos (ej. agrupa alimentos, descarta info irrelevante) y consulta la calculadora determinista de bolos.
3.  **Interacción**:
    *   El Bot envía un mensaje: *"Detectada comida: 60g carbohidratos. Basado en tu glucosa actual (110 →), sugiero 4.5u."*
    *   **Botones**: `[✅ Aprobar 4.5u]` `[✏️ Editar]` `[❌ Ignorar]`
4.  **Acción**: Si el usuario aprueba, se registra el tratamiento automáticamente.

### Caso 2: Asesoramiento Proactivo (Pre-comida)
1.  **Contexto**: El sistema sabe que el usuario suele almorzar a las 14:00.
2.  **Análisis (13:30)**:
    *   Si Glucosa es 100 estable -> No hace nada.
    *   Si Glucosa es 160 y subiendo -> **Alerta Preventiva**.
3.  **Mensaje**: *"Son las 13:30. Estás en 160mg/dL. Si vas a comer a las 14:00, sería ideal corregir o adelantar el bolo ahora para evitar un pico post-prandial."*

### Caso 3: Alerta de Tendencia (Sin Comida)
*   Detecta subida rápida sin bolus/comida activa: *"Estás subiendo rápido (↑↑). ¿Estrés o fallo de infusión? Revisa cetonas si persiste."*

## 4. Consideraciones Técnicas y Limitaciones de Red

Dado que la conectividad puede ser inestable:
1.  **Comunicación Ligera**: Los mensajes de texto de Telegram consumen muy pocos datos.
2.  **Gestión de "Timeout"**: Si el backend intenta contactar a Telegram y falla (sin red), debe tener una cola de reintento inteligente (no bombardear cuando vuelva la red, solo enviar el último estado relevante).
3.  **Fallbacks**: Si el asistente no responde, la App principal (local) siempre debe funcionar como respaldo manual completo.
4.  **Seguridad**: El Bot solo responderá al ID de usuario específico (whitelisting) para evitar accesos no autorizados.

## 5. Próximos Pasos de Investigación
*   Definir librería de Python para el Bot (`python-telegram-bot` o similar).
*   Diseñar el formato del JSON intermedio para intercambio de datos.
*   Estudiar patrones de "aprendizaje" para que la IA detecte los horarios de comida automáticamente.
