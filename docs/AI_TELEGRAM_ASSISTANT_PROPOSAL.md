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
7.  **Auditoría**: Acceso al motor de sugerencias (`suggestion_engine`) para proponer cambios en ratios o sensibilidad basados en historial.

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

### Caso 4: Monitorización de Bolo Doble (Combo/Extendido)
Gestionar los recordatorios y ajustes de la segunda parte de un bolo extendido (ej. para comidas altas en proteínas/grasas como pizza).
1.  **Detección**: El usuario registra un bolo combo (ej. 50% ahora, 50% en 2 horas).
2.  **Vigilancia**: 15 minutos antes de la hora programada para la segunda dosis.
3.  **Análisis Inteligente**:
    *   **Escenario A (Subida Anticipada)**: Glucosa ya subiendo antes de tiempo.
        *   *Mensaje*: "Faltan 15 min para tu bolo extendido, pero ya estás subiendo. ¿Quieres adelantarlo ahora?"
    *   **Escenario B (Hipoglucemia)**: Glucosa bajando o demasiado baja.
        *   *Mensaje*: "CUIDADO: Toca el resto del bolo en 15 min, pero estás en 80 mg/dL y estable. ¿Posponemos o cancelamos?"
    *   **Escenario C (Estable)**: "Todo en orden. Recordatorio: el resto del bolo se administra en 15 min."

### Caso 5: Gestión Inteligente de Basal (Lenta)
Evitar olvidos o dosis dobles de la insulina basal diaria (ej. Tresiba/Lantus).
1.  **Recordatorio Contextual**:
    *   Si a la hora habitual (ej. 22:00) no se ha registrado la dosis: *"Hola, son las 22:00. ¿Te pusiste la basal (15u)?"*
    *   **Botón Rápido**: `[✅ Sí, registrar]` `[⏰ 15 min más tarde]`
2.  **Seguridad (Anti-doble dosis)**:
    *   Si el usuario intenta registrar una basal y el sistema ve que ya se puso una hace 2 horas: *"⚠️ ALERTA: Ya registraste una dosis de basal hoy a las 20:00. ¿Seguro que es otra?"*
3.  **Recuperación de Olvidos (Integración con Función de Recálculo)**:
    *   Si el usuario responde al recordatorio 3 horas tarde: *"Veo que han pasado 3 horas de tu hora habitual. He consultado a la App y recalculado la dosis para evitar solapamiento mañana."*
    *   *Acción*: La IA invoca `calculate_late_basal(hours_late=3)` → La App devuelve `13.5u` (en lugar de 15u).
    *   *Mensaje*: *"La dosis ajustada es 13.5u (reducida por el retraso). ¿Registramos esta cantidad?"*

### Caso 6: Interacción Multimodal (Fotos de Comida)
Eliminar la entrada manual de datos mediante visión artificial.
1.  **Acción**: El usuario envía una foto del plato o etiqueta al chat.
2.  **Enrutamiento**: La IA detecta la imagen e invoca directamente al servicio de "Escáner/Visión" de la App.
3.  **Resultado**:
    *   IA: "He analizado la foto: Plato de lentejas (aprox 300g) + Pan."
    *   IA: "Estimación total: **45g Carbohidratos**."
    *   IA: "¿Calculamos bolo para 45g?"
4.  **Comparativa Carta vs Realidad**:
    *   Si el usuario primero envía foto del menú y luego del plato servido, la IA compara: *"¡Ojo! El plato es más grande de lo esperado (+15g hidratos). Sugiero añadir 1.5u extra."* (Lógica basada en `restaurant.py`).

### Caso 7: Asistencia de Microbolos (Gestión de Curva Fina)
Actuar como un "Lazo Cerrado Asistido" para correcciones pequeñas y precisas.
1.  **Escenario**: No hay hiperglucemia severa (ej. 135 mg/dL) pero hay una tendencia de subida lenta y constante.
2.  **Análisis**: El sistema predice que en 1 hora estará en 180 mg/dL si no hace nada.
3.  **Sugerencia de Precisión**: *"Veo una subida lenta sostenida. Para mantener la línea plana y no salir de rango, sugiero un microbolo de **0.35u** ahora."*
4.  **Valor**: Permite al usuario "aplanar la curva" con seguridad, validando manualmente las micro-dosis que un sistema automático pondría solo.

### Caso 8: Resumen Matutino (Feedback Diario)
Para cerrar el ciclo y motivar, el Bot envía un reporte breve cada mañana.
1.  **Trigger**: 08:00 AM (o al despertar).
2.  **Contenido**:
    *   Resumen de la noche: *"Noche estable (100-120). Sin alertas."*
    *   **Evaluación Basal**: *"Tu basal de anoche (15u) te mantuvo plana (variación <10mg). Parece la dosis correcta."* (O avisará si hubo deriva hacia arriba/abajo).
    *   Estadística Ayer: *"Ayer estuviste un **85% en rango**. ¡Muy bien!"*
    *   Recordatorios hoy: *"Hoy es día de cambio de sensor/catéter."* (Si toca).

## 5. Consideraciones Técnicas y Limitaciones de Red

Dado que la conectividad puede ser inestable:
1.  **Comunicación Ligera**: Los mensajes de texto de Telegram consumen muy pocos datos.
2.  **Gestión de "Timeout"**: Si el backend intenta contactar a Telegram y falla (sin red), debe tener una cola de reintento inteligente (no bombardear cuando vuelva la red, solo enviar el último estado relevante).
3.  **Fallbacks**: Si el asistente no responde, la App principal (local) siempre debe funcionar como respaldo manual completo.
4.  **Seguridad**: El Bot solo responderá al ID de usuario específico (whitelisting) para evitar accesos no autorizados.

## 5. Aprendizaje y Adaptación de Horarios (Training)
Para que las "Alertas Preventivas" (Caso 2) sean útiles y no molestas, el sistema debe aprender los hábitos del usuario.

### Mecanismo de Aprendizaje
*   **Análisis Histórico**: El sistema analizará las últimas semanas de registros de comidas en la base de datos para identificar patrones (clusters) de horarios.
    *   *Ejemplo*: "Usuario suele comer lunes a viernes entre 13:45 y 14:15".
    *   *Ejemplo*: "Sábados y domingos come entre 14:30 y 15:30".
*   **Diferenciación Laboral/Festivo**: Distinguir comportamientos entre días de semana y fines de semana.
*   **Feedback Loop (Refuerzo)**:
    *   Si el bot sugiere adelantar el bolo a las 13:30 y el usuario dice "No voy a comer todavía", el sistema aprende que hoy es una excepción.
    *   Si el usuario confirma, refuerza el patrón horario.

## 6. Filosofía del Asistente: "El Compañero Transparente"

Más que un bot de alertas, buscamos un **"Compañero de Fatiga"** que reduzca la carga mental diaria.

### A. Explicabilidad ("El Porqué")
El asistente nunca debe dar una orden "caja negra". Siempre debe justificar su razonamiento para educar y dar tranquilidad al usuario.
*   *Mal ejemplo*: "Ponte 2 unidades ahora."
*   *Buen ejemplo*: "Sugiero adelantar 2u del bolo *porque* tu glucosa de partida es más alta de lo habitual (150) y el cálculo de IOB muestra que no tienes insulina activa suficiente para cubrirlo."

### B. Tranquilidad y Carga Mental
El asistente debe usar un lenguaje que transmita seguridad y control.
*   *Frase clave*: "No te preocupes, yo te monitorizo y te aviso si la predicción de hipoglucemia se confirma. Descansa."
*   *Objetivo*: Que el usuario pueda dejar de mirar el monitor cada 5 minutos, sabiendo que "alguien" está vigilando.

### C. Integración Profunda y Auditoría
El asistente no es solo una capa superficial; tiene acceso directo a los motores matemáticos de la app (`autotune`, `curves`, `isf_calc`). 
Debe informar sobre el estado interno de estos cálculos:
1.  **Auditoría de Cambios**: "He detectado mayor sensibilidad esta semana. He ajustado tu ISF de 40 a 45 para los cálculos de hoy. ¿Te parece correcto?"
2.  **Estado de Absorción**: "Tus curvas de absorción indican que la pizza de anoche tardó 4h en digerirse, tenlo en cuenta para la próxima vez (quizás extender más el bolo)."
3.  **Predicción de Riesgos**: "Hay riesgo de hipo *porque* tu IOB es alto (3.5u) y la comida anterior ya se absorbió casi toda."

### D. Flexibilidad y Gestión de Errores (Conversación Natural)
El sistema debe ser tolerante a fallos humanos y cambios de opinión, aprovechando la capacidad de la IA para entender el contexto.
*   **Corrección de Errores**:
    *   *Usuario*: "Te he pasado la foto mal, esa era la de mi amigo."
    *   *IA*: "Entendido, descarto el cálculo anterior. Mándame tu foto correcta cuando quieras."
*   **Reinicio de Contexto ("Reset")**:
    *   *Usuario*: "Olvida todo lo de la pizza, al final voy a pedir ensalada."
    *   *IA*: "Vale, borro el registro temporal de pizza. ¿Cuántos hidratos tiene la ensalada o quieres que la estime?"
*   **Alternativas**:
    *   Si la IA duda (confianza baja en foto), ofrece opciones: *"No veo claro si es pan o patata. Si es pan son 30g, si es patata 45g. ¿Cuál elijo?"*

### E. Comportamiento "Sombra Inteligente" (Iniciativa y Discreción)
Para no ser intrusivo, el asistente aplica un filtro de relevancia antes de hablar:
*   **Silencio por Defecto**: Si todo va bien, no dice nada. Su silencio es la confirmación de que estás seguro.
*   **Filtro Anti-Fatiga**: Evita bombardear. Si ya notificó una subida leve, no volverá a avisar en 45 min salvo que la situación empeore drásticamente.
*   **Iniciativa Autónoma**: No espera órdenes para proponer mejoras evidentes.
    *   *Ejemplo*: Si detecta 3 noches seguidas de bajada, tomará la iniciativa de sugerir una reducción de basal en el resumen matutino, sin que tú lo pidas.
    *   *Objetivo*: Que sientas que "alguien" piensa en tu diabetes para que tú no tengas que hacerlo tanto.

## 7. Próximos Pasos de Investigación
*   Definir librería de Python para el Bot (`python-telegram-bot` o similar).
*   Diseñar el formato del JSON intermedio para intercambio de datos.
*   Implementar algoritmo básico de clustering (K-Means simple) para deducir horarios habituales.

## 8. Optimización para Entornos Gratuitos (Render/Neon)
Dado que operamos en infraestructura "Free Tier", la eficiencia es crítica para evitar cortes por límites de uso.

### A. Estrategia "Wake-on-Demand" (Render)
Los servicios gratuitos de Render se "duermen" tras inactividad.
*   **Problema**: Si el bot duerme, no puede avisar.
*   **Solución Híbrida (VALIDADA)**:
    *   Actualmente el usuario ya utiliza un **servicio externo "ping"** que mantiene activo el backend con éxito. Mantener esta estrategia.
    *   **Polling Inteligente Nightscout**: No chequear cada minuto. Hacerlo cada 5 minutos (coincidiendo con las lecturas de Dexcom/Libre) para minimizar uso de CPU/RAM.

### B. Base de Datos Ligera (Neon Postgres)
*   **Limpieza de Datos**: No guardar "todo". Purgar logs antiguos de la conversación con el bot (retención de 7 días).
*   **Caché en Memoria**: Cargar las curvas ISF/IC en memoria al inicio para no consultar a Neon en cada mensaje del chat. Solo escribir en DB cuando se confirma un tratamiento real.

### C. Procesamiento Asíncrono
*   Evitar procesos pesados de IA en tiempo real.
*   Los "re-cálculos" de curvas o aprendizajes de horarios se programarán para correr **una vez al día** (job nocturno) y guardar resultados estáticos, en lugar de calcularse cada vez que el usuario come.

## 9. Análisis de Viabilidad Técnica (Reality Check)
Tras revisar el stack actual (Python/FastAPI, Render Free, Neon, Gemini), el veredicto es: **PROYECTO VIABLE**.

### Factores Críticos y Soluciones:
1.  **Conexión Telegram (Sleep Mode)**:
    *   *Riesgo*: En Render, el polling tradicional puede fallar si el proceso se duerme o reinicia.
    *   *Solución*: Usar **Webhooks**. Telegram "despierta" a tu app enviando una petición HTTP cada vez que escribes. Para la iniciativa propia (alertas), el servicio de "Ping" externo garantiza que el proceso siga vivo.
2.  **Memoria RAM (Límite 512MB)**:
    *   *Riesgo*: Correr FastAPI + Bot + Análisis de Datos puede saturar la memoria gratuita.
    *   *Mitigación*: Código eficiente. No cargar grandes librerías de Data Science innecesarias en memoria. Usar `asyncio` para compartir recursos.
3.  **Costes IA (Gemini)**:
    *   *Estado*: El tier gratuito de Gemini es más que suficiente para un uso personal (hasta 60 peticiones/minuto). No habrá cost.
4.  **Latencia (Cold Starts)**:
    *   *Realidad*: La primera respuesta tras un rato de silencio puede tardar 2-3 segundos (conexión a DB Neon "despertando"). Es asumible para un asistente personal.

### Estrategia de Modelos IA: Selección Dinámica (Gemini 3.0)
El sistema utilizará la nueva suite Gemini 3.0 para balancear velocidad e inteligencia profunda.

1.  **Modelo "Táctico" (`gemini-3.0-flash`)**:
    *   *Uso*: Visión (Escáner de comida), Chat diario, Respuestas rápidas (<1s).
    *   *Ventaja*: Máxima eficiencia de tokens. Será el "caballo de batalla" (95% de las peticiones).

2.  **Modelo "Estratégico" (`gemini-3.0-pro`)**:
    *   *Uso*: "Razonamiento Profundo". Solo se invoca para análisis complejos de patrones, dudas médicas difíciles o cuando el modelo Flash tiene baja confianza.
    *   *Filosofía*: Reservar la potencia máxima para los momentos críticos.

3.  **¿Por qué no un modelo Local (Llama 2) en Render?**:
    *   **Imposibilidad Física**: Render Free ofrece **0.5 GB** de RAM. Un modelo como Llama 2 (incluso pequeño) requiere mínimo **4 GB**.
    *   *Resultado*: Intentar correrlo tumbaría tu servidor al instante (`Out Of Memory`).
    *   *Veredicto*: Nos quedamos con Gemini Flash/Pro. Es la única opción viable, inteligente y gratuita para tu infraestructura actual.

**Conclusión Final**: El proyecto es técnicamente robusto, económicamente viable (Free Tier) y utiliza tecnología de vanguardia (Gemini 3.0) con una arquitectura de seguridad por capas.

## 10. Estrategia de Implantación Segura (Risk Zero)
Para garantizar que la App actual (crítica para la salud) no sufra interrupciones, seguiremos un despliegue "Quirúrgico":

1.  **Código Aditivo (No Invasivo)**:
    *   Todo el código del asistente irá en un nuevo módulo aislado (`app/bot/`).
    *   Los servicios "Core" actuales (`bolus_engine`, `isf`, `curves`) se tratarán como **Solo Lectura**. El bot los "usa" importándolos, pero no modifica ni una línea de su lógica interna.
2.  **Feature Flag (Interruptor de Apagado)**:
    *   El bot se encenderá mediante una variable de entorno (`ENABLE_TELEGRAM_BOT=true`).
    *   Si surge cualquier problema de rendimiento o memoria, con solo cambiar esa variable a `false`, el sistema apaga el bot y la app sigue funcionando como siempre.
3.  **Fases de Despliegue**:
    *   *Fase 1 (Observador Pasivo)*: El bot solo lee (Nightscout, IOB) y te contesta, pero **NO** tiene permiso para escribir tratamientos en la base de datos.
    *   *Fase 2 (Escritura)*: Solo tras verificar que la Fase 1 no afecta a la RAM ni a la estabilidad, habilitaremos la capacidad de registrar bolos.
