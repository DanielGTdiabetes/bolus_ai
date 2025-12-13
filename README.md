# Bolus AI

Backend FastAPI con autenticación básica y preparación para PWA.

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
  curl -X POST http://localhost:8000/api/auth/me/password \
    -H "Authorization: Bearer <token>" \
    -H "Content-Type: application/json" \
    -d '{"password":"nuevaPasswordSegura"}'
  ```
- Para crear usuarios manualmente edita `backend/data/users.json` siguiendo el esquema.

## Despliegue en Render

1. Crea los servicios desde `render.yaml` (Blueprint). Render generará un **Web Service** `bolus-ai-backend` con entorno **python** (build con `pip install -r backend/requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, `healthCheckPath=/api/health`, región Frankfurt, plan Starter) y un **Static Site** `bolus-ai-frontend` que ejecuta `npm ci && npm run build` en `frontend/` y publica `frontend/dist`.
2. Render debe usar **Python 3.11**. El archivo `backend/runtime.txt` fija la versión (`python-3.11.9`) y la instalación de dependencias usa `backend/requirements.txt`.
2. Configura las variables de entorno del backend:
   - `JWT_SECRET`: márcala como *Sync: false* y usa **Generate** en Render.
   - `NIGHTSCOUT_URL`: opcional, deja `""` si no se usa.
   - `DATA_DIR=/var/data`: ya viene definido en el blueprint.
3. El backend necesita persistencia: `render.yaml` monta el disco `bolus-data` en `/var/data` (1 GB). Déjalo habilitado para conservar `settings.json`, `users.json`, etc.
4. El frontend obtiene `VITE_API_BASE_URL` automáticamente desde el servicio backend gracias a `fromService: property: url`; no necesitas configurarlo a mano salvo que anules la URL.
5. Enrutamiento SPA: el archivo `frontend/public/_redirects` (copiado automáticamente a `frontend/dist/_redirects` por Vite) fuerza el rewrite `/* -> /index.html 200`, necesario para que Render sirva correctamente las rutas del frontend.
6. HTTPS es obligatorio: usa siempre la URL `https://...onrender.com` para el frontend y cualquier integración externa.

## Datos y persistencia
- En local, el backend guarda los JSON en `backend/data` (o en la ruta indicada por `DATA_DIR`).
- En Render, `DATA_DIR` se fija a `/var/data` y se monta un disco llamado `bolus-data` para persistir `settings.json`, `users.json`, `events.json`, `changes.json` y `sessions.json`.
- Docker Compose ya mapea `./config/config.json` y un volumen nombrado `backend_data` a `/app/backend/data` para mantener los datos entre reinicios.

## Endpoints principales
- `POST /api/auth/login` → JWT access/refresh
- `POST /api/auth/refresh` → nuevo access token
- `GET /api/auth/me` → usuario autenticado
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
