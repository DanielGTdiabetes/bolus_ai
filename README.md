# Bolus AI

Backend FastAPI con autenticación JWT y frontend estático minimalista.

## Estructura
```
bolus-ai/
  backend/
  config/
  docker-compose.yml
  docs/SECURITY.md
```

## Configuración rápida
1. Copia el archivo de ejemplo y ajusta los valores:
   ```bash
   cp config/config.example.json config/config.json
   ```
2. Exporta `JWT_SECRET` (obligatorio en producción) y opcionalmente `DATA_DIR`, `JWT_ISSUER`, `CORS_ORIGINS`.
3. Arranca con Docker Compose:
   ```bash
   docker compose up --build
   ```
   El backend escucha en `http://localhost:8000`.

## Usuarios
- Si `backend/data/users.json` no existe, se crea uno con `admin / admin123` y `needs_password_change=true`.
- Cambia la contraseña con:
  ```bash
  curl -X POST http://localhost:8000/api/auth/change-password \
    -H "Authorization: Bearer <token>" \
    -H "Content-Type: application/json" \
    -d '{"old_password":"admin123", "new_password":"nuevaPasswordSegura"}'
  ```
- Para crear usuarios manualmente edita `backend/data/users.json` siguiendo el esquema. Las contraseñas se guardan con hash bcrypt.

## Despliegue en Render

1. Crea los servicios desde `render.yaml` (Blueprint). Render generará un **Web Service** `bolus-ai-backend` con entorno **python** (build con `pip install -r backend/requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, `healthCheckPath=/api/health`, región Frankfurt, plan Starter) y un **Static Site** `bolus-ai-frontend` que ejecuta `npm ci && npm run build` en `frontend/` y publica `frontend/dist`.
2. Render debe usar **Python 3.11**. El archivo `backend/runtime.txt` fija la versión (`python-3.11.9`) y la instalación de dependencias usa `backend/requirements.txt`.
2. Configura las variables de entorno del backend:
   - `JWT_SECRET`: márcala como *Sync: false* y usa **Generate** en Render.
   - `NIGHTSCOUT_URL`: opcional, deja `""` si no se usa.
   - `DATA_DIR=/var/data`: ya viene definido en el blueprint.
3. El backend necesita persistencia: `render.yaml` monta el disco `bolus-data` en `/var/data` (1 GB). Déjalo habilitado para conservar `settings.json`, `users.json`, etc.
4. El frontend obtiene `VITE_API_BASE_URL` automáticamente desde el servicio backend gracias a `fromService: property: url`; no necesitas configurarlo a mano salvo que anules la URL.
5. Enrutamiento SPA: el archivo `frontend/public/_redirects` (copiado automáticamente a `frontend/dist/_redirects`) fuerza el rewrite `/* -> /index.html 200`, necesario para que Render sirva correctamente las rutas del frontend.
6. HTTPS es obligatorio: usa siempre la URL `https://...onrender.com` para el frontend y cualquier integración externa.

## Render (Backend Docker)

Si prefieres desplegar solo el backend como imagen Docker en Render:

1. Crea un **Web Service** nuevo y selecciona entorno **Docker**.
2. Indica el `Dockerfile Path` como `backend/Dockerfile` (Render usará la raíz del repo como *build context*).
3. Añade las variables de entorno:
   - `JWT_SECRET` → usa la opción **Generate** de Render.
   - `DATA_DIR=/tmp/data` para el plan gratuito sin disco persistente.
4. No necesitas definir **Start Command** porque ya está incluido en el `Dockerfile`.

## Datos y persistencia
- En local, el backend guarda los JSON en `backend/data` (o en la ruta indicada por `DATA_DIR`).
- En Render, `DATA_DIR` se fija a `/var/data` y se monta un disco llamado `bolus-data` para persistir `settings.json`, `users.json`, `events.json`, `changes.json` y `sessions.json`.
- Docker Compose ya mapea `./config/config.json` y un volumen nombrado `backend_data` a `/app/backend/data` para mantener los datos entre reinicios.

## Endpoints principales
- `POST /api/auth/login` → devuelve `{access_token, token_type, user}`
- `GET /api/auth/me` → usuario autenticado
- `POST /api/auth/change-password` → requiere token, valida contraseña actual
- `GET /api/settings` (auth requerido)
- `PUT /api/settings` (rol admin)
- `GET /api/changes` (auth)
- `POST /api/bolus/recommend` (auth)

## Pruebas
```bash
cd backend
python -m pytest -q
```
(Si faltan dependencias en tu entorno, instala `pip install -r requirements.txt`.)

## Seguridad
Consulta `docs/SECURITY.md` para detalles sobre decisiones y despliegue seguro.

## Integración Nightscout
El sistema permite configurar una instancia de [Nightscout](http://nightscout.info/) para obtener:
1. **Glucosa actual (SGV)**: se usará si no introduces un valor manual.
2. **Tratamientos recientes**: para calcular la insulina activa (IOB).

### Configuración
1. Inicia sesión en Bolus AI.
2. Ve al menú "Configuración".
3. Activa la casilla "Integración Nightscout".
4. Introduce la **URL** de tu sitio Nightscout (ej. `https://mi-ns.herokuapp.com`).
5. Introduce tu **API Secret** (token de acceso).
   - Puedes crear un token en Nightscout (Admin Tools > Subjects > Edit > Create Subject/Token) con el rol `readable`.
   - O usar tu `API_SECRET` principal (menos recomendado).
   - Bolus AI nunca muestra el token guardado en la interfaz.
6. Haz clic en "Probar conexión" para verificar.
7. Guarda los cambios.

**Permisos necesarios**:
- El token debe tener permisos de lectura simples (`readable` o similar) para acceder a glusosa y tratamientos.

**Nota sobre persistencia en Render Free:** Si usas el plan gratuito de Render sin disco persistente, la configuración se perderá al reiniciarse el servicio (ya que se guarda en `DATA_DIR`). Se recomienda usar un disco persistente (`bolus-data`).

## Foto del plato (Visión IA)
El sistema incluye una función experimental para estimar carbohidratos a partir de una foto del plato usando OpenAI Vision.

### Configuración requerida
Para que funcione, debes configurar la siguiente variable de entorno en el backend (o en Render):
- `OPENAI_API_KEY`: Tu clave de API de OpenAI (debe tener acceso a GPT-4o / Vision).

### Funcionamiento
1. Sube una imagen desde la dashboard ("Foto del plato").
2. El sistema analiza los alimentos y estima los carbohidratos.
3. Si detecta **alto contenido graso/proteico** (pizza, hamburguesa, etc.), sugerirá un **Bolo Extendido** (ej. 60% ahora y 40% en 2 horas).
4. **Privacidad**: Las imágenes se procesan en memoria y se envían a OpenAI para el análisis, pero **NO se guardan en el servidor** de Bolus AI.

### Descargo de responsabilidad
La estimación es solo una ayuda y puede contener errores. Siempre verifica los valores antes de administrar insulina.
