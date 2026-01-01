# 🤖 Guía de Configuración: Bot de Telegram

Esta guía describe cómo crear tu propio Bot de Telegram y conectarlo con **Bolus AI** para disfrutar de todas las funciones de asistencia IA (registro por voz, análisis de fotos y alertas proactivas).

---

## 🏗️ 1. Crear el Bot en Telegram (BotFather)

1.  Abre la aplicación de **Telegram**.
2.  En el buscador, escribe `@BotFather` y selecciona el bot oficial (tiene un icono de verificado azul 🔵).
3.  Pulsa **Iniciar** (o escribe `/start`).
4.  Escribe el comando `/newbot`.
5.  **Nombre visible**: Elige cómo se llamará tu asistente (ej: `Mi Bolus AI`).
6.  **Nombre de usuario (username)**: Debe ser único y terminar en `bot` (ej: `daniel_diabetes_bot`).
7.  ¡Listo! BotFather te dará un mensaje con tu **TOKEN**.
    *   Será algo como: `123456789:ABCdefGHIjklMNOpqrsTUVwxyZ`.
    *   ⚠️ **Copia este Token**, lo necesitarás para Render.

---

## 🆔 2. Obtener tu Chat ID (Tu Identificador)

Para que el Bot solo te responda a ti y nadie más pueda acceder a tus datos médicos, necesitas decirle quién es el "Dueño".

1.  Busca tu nuevo bot en Telegram (ej: `@daniel_diabetes_bot`) y pulsa **Iniciar**.
2.  Escribe cualquier cosa (ej: "Hola").
3.  Ahora, busca otro bot llamado `@userinfobot` (o `@ShowJsonBot`).
4.  Inícialo o reenvíale el mensaje. Te devolverá un número, que es tu **Id**.
    *   Ejemplo: `987654321`.
    *   ⚠️ **Anota este número**.

> *Alternativa*: Simplemente espera a configurar el bot en la app, y si escribes al bot este rechazará el mensaje diciendo "User unauthorized (ID: 987654321)". Ese es tu ID.

---

## ☁️ 3. Configuración en Render

Sigue estos pasos para conectar el "cerebro" (la App) con el "cuerpo" (Telegram).

1.  Ve a tu Dashboard en **[Render.com](https://render.com)**.
2.  Entra en tu servicio **bolus-ai**.
3.  Ve a la pestaña **Environment**.
4.  Añade (o edita) las siguientes Variables de Entorno:

| Variable | Valor (Ejemplo) | Descripción |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | `123456789:ABC...` | El token que te dio BotFather. |
| `TELEGRAM_ALLOWED_USER` | `987654321` | Tu Chat ID personal (Numérico). |
| `GOOGLE_API_KEY` | `AIzaSyD...` | Tu clave de Gemini (Google AI Studio). |

5.  Pulsa **Save Changes**. Render reiniciará la aplicación automáticamente.

---

## 🧠 4. Configurar la IA (Google Gemini)

Para que el Bot pueda entender tus audios ("Me he comido un plátano") y analizar fotos de comida, necesitas el motor de inteligencia de Google.

1.  Ve a **[Google AI Studio](https://aistudio.google.com/)**.
2.  Inicia sesión con cualquier cuenta de Google.
3.  Haz clic en **"Get API Key"** -> **"Create API Key in new project"**.
4.  Copia la clave que empieza por `AIza...`.
5.  Pégala en Render en la variable `GOOGLE_API_KEY`.

> **Nota**: El plan gratuito de Gemini es más que suficiente para uso personal.

---

## ✅ 5. Verificación

Una vez Render haya reiniciado (puedes ver "Live" en los logs):

1.  Abre tu Bot en Telegram.
2.  Escribe `/start`.
3.  El Bot debería responderte: *"🩸 Bienvenido a Bolus AI"*.
4.  Prueba a enviar un mensaje de voz o una foto de comida.
