# ☁️ Despliegue en Render (Modo Respaldo / Cloud)

Esta guía explica cómo desplegar **Bolus AI** en Render para que actúe como **Backup de Emergencia** o instancia secundaria.
*Si buscas la configuración principal, ve a la [Guía NAS](./NAS_SETUP.md).*

## 1. Preparación del Repositorio
Asegúrate de tener el código en un repositorio de **GitHub** o **GitLab**. Render se conectará a este repositorio para descargar y ejecutar la aplicación.

## 2. Crear el Servicio Web (Backend + Frontend)
Bolus AI está configurado para ejecutarse como un único servicio que sirve tanto el servidor (API) como la interfaz visual.

1. Inicia sesión en [Render.com](https://render.com/).
2. Haz clic en **New +** y selecciona **Web Service**.
3. Conecta tu repositorio de GitHub.
4. Configura los siguientes campos:
   - **Name**: `bolus-ai` (o el que prefieras).
   - **Region**: Selecciona la más cercana a ti (ej. `Frankfurt` si estás en España).
   - **Language**: `Python`.
   - **Root Directory**: Dejar vacío (raíz del proyecto).
   - **Build Command**: `chmod +x build_render.sh && ./build_render.sh`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: `Starter`.
   - **AutoDeploy**: `No` (o desactívalo en Settings después).

> **⚠️ IMPORTANTE: AHORRO DE COSTES**
> Hemos configurado el archivo `render.yaml` con `autoDeploy: false`.
> Esto significa que tus cambios **NO** se subirán automáticamente.
> Cuando quieras actualizar la versión pública, debes ir a tu Dashboard en Render y pulsar **"Manual Deploy"**.
> Esto evita que gastes tus 500 minutos gratuitos con pequeños cambios de desarrollo.

## 3. Variables de Entorno (Environment Variables)
Estas son las "instrucciones" secretas que necesita la app para funcionar. En Render, ve a la pestaña **Environment** y añade las siguientes:

| Variable | Valor / Instrucción | Importante |
| :--- | :--- | :--- |
| `JWT_SECRET` | Haz clic en "Generate" en Render | Única para tu seguridad. |
| `APP_SECRET_KEY` | Una clave aleatoria larga | Sirve para cifrar datos sensibles. |
| `PYTHON_VERSION` | `3.11.0` | Versión necesaria del lenguaje. |
| `NODE_VERSION` | `20.10.0` | Versión necesaria para construir el frontend. |
| `DATA_DIR` | `/var/data` | Carpeta donde se guardarán tus configuraciones. |
| `GOOGLE_API_KEY` | Tu clave de Google Gemini | **Opcional** (Para análisis de fotos gratis). |
| `OPENAI_API_KEY` | Tu clave de OpenAI | **Opcional** (Alternativa a Gemini). |
| `TELEGRAM_BOT_TOKEN` | Token de BotFather | **Opcional** (Para activar el Bot). |
| `TELEGRAM_ALLOWED_USER` | Tu ID de Telegram | **Opcional** (Seguridad del Bot). |
| `NIGHTSCOUT_URL` | URL de tu Nightscout | **Opcional** (ej. `https://mi-ns.herokuapp.com`). |

## 4. Persistencia de Datos (Disco)
Si usas el plan **Starter**, debes añadir un disco para que tus usuarios, configuraciones e historial no se borren.

1. Ve a la pestaña **Disk**.
2. Haz clic en **Add Disk**.
3. Configuración:
   - **Name**: `bolus-data`
   - **Mount Path**: `/var/data`
   - **Size**: `1 GB` (es más que suficiente).

## 5. ¡Listo!
Haz clic en **Create Web Service**. Render tardará unos minutos en construir la aplicación. Una vez termine, te dará una URL (ej. `https://bolus-ai-xxxx.onrender.com`).

---

### 💡 Tips Adicionales
- **Acceso Inicial**: El usuario por defecto es `admin` y la contraseña es `admin123`. El sistema te pedirá cambiarla al entrar por primera vez.
- **Bot de Telegram**: ¿Quieres activar la IA por voz y fotos? 👉 **[Consulta la Guía de Telegram](./docs/TELEGRAM_SETUP.md)**.
- **Nightscout**: No es obligatorio poner la URL en las variables de entorno; puedes configurarlo después directamente desde la pantalla de ajustes dentro de la aplicación.
- **Análisis de Fotos**: Se recomienda usar **Google Gemini** por ser más rápido y tener un plan gratuito generoso. Consigue tu clave en [Google AI Studio](https://aistudio.google.com/).
