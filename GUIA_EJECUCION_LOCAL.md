# Guía de Ejecución Local para Bolus AI

Para trabajar en el proyecto sin consumir minutos de Render, sigue estos pasos utilizando dos terminales separadas.

## 1. Backend (Servidor Python)
Este es el "cerebro" de la aplicación. Debe estar corriendo para que la web funcione y guarde datos.

1. Abre una terminal (PowerShell o CMD).
2. Navega a la carpeta principal del proyecto:
   ```powershell
   cd d:\bolus_ai\bolus_ai
   ```
3. Ejecuta el servidor:
   ```powershell
  añade tambien, de insulina Novorapid 
   ```
   _(Si tienes un entorno virtual activo, asegúrate de usarlo, pero si `python` funciona directo, adelante)._

Deberías ver un mensaje que dice `Application startup complete`.

---

## 2. Frontend (Interfaz Web)
Esta es la "cara" de la aplicación que ves en el navegador.

1. Abre **otra** terminal nueva.
2. Navega a la carpeta del frontend:
   ```powershell
   cd d:\bolus_ai\bolus_ai\frontend
   ```
3. Inicia el modo desarrollo:
   ```powershell
   npm run dev
   ```

Verás un mensaje indicando que la web está disponible en:
👉 **http://localhost:5173/**

---

## 3. Ver la App
Simplemente abre tu navegador (Chrome, Edge, etc.) y ve a:
**[http://localhost:5173/](http://localhost:5173/)**

Todos los cambios que hagas en el código se reflejarán automáticamente aquí casi al instante.

## Nota sobre Render (Nube)
Hemos desactivado el `autoDeploy` para ahorrar minutos gratuitos.
* **Trabaja siempre en Local.**
* Cuando quieras actualizar la versión pública (internet), ve al panel de control de Render y pulsa **"Manual Deploy"**.
