# Configuración de Visión IA con Gemini

Bolus AI permite utilizar **Gemini (Google)** como alternativa a OpenAI para la función de "Foto del plato". Gemini 1.5 Flash es una opción muy rápida y económica (actualmente con un generoso *tier* gratuito).

## Pasos para configurar Gemini

### 1. Obtener la API Key de Google
1. Visita [Google AI Studio](https://aistudio.google.com/).
2. Inicia sesión con tu cuenta de Google.
3. Haz clic en el botón **"Get API key"** (o "Create API key").
4. Copia la clave generada (empieza por `AIzp...`).

### 2. Configurar Bolus AI
Debes definir (o actualizar) las siguientes variables de entorno en tu despliegue (Render, Docker, o local).

| Variable | Valor | Descripción |
| :--- | :--- | :--- |
| `VISION_PROVIDER` | `gemini` | Indica al sistema que use Google Gemini en lugar de OpenAI. |
| `GOOGLE_API_KEY` | `Tu_Clave_Copiada` | La clave que obtuviste en el paso 1. |
| `GEMINI_MODEL` | `gemini-1.5-flash-001` | (Opcional) Modelo a usar. Por defecto `gemini-1.5-flash-001`. |

*(Nota: Si usas `config.json` localmente, no es necesario editarlo si exportas estas variables en tu terminal antes de arrancar, o puedes añadirlas a tu gestor de secretos).*

### 3. Reiniciar el servicio
Una vez guardadas las variables, reinicia el backend de Bolus AI para que aplique los cambios.

### 4. Verificar
1. Ve a la pantalla principal de Bolus AI.
2. Usa la tarjeta "Foto del plato".
3. Sube una imagen. Si el análisis funciona y ves los resultados, Gemini está operando correctamente.

---

## Comparativa rápida

| Proveedor | Modelo usado | Coste | Velocidad |
| :--- | :--- | :--- | :--- |
| **OpenAI** (Default) | GPT-4o | Pago por uso (Créditos OpenAI) | Muy alta |
| **Google** | Gemini 1.5 Flash | **Gratuito** (hasta ciertos límites en AI Studio) | Extremadamente alta |

**Recomendación:** Para uso personal de Bolus AI, **Gemini** es la opción recomendada por su coste cero en el tier gratuito y excelente capacidad de visión.
