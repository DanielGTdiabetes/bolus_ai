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

1. Crea los servicios desde `render.yaml` (Blueprint). Render creará:
   - **Web Service** `bolus-ai-backend` usando `backend/Dockerfile`, con `healthCheckPath=/api/health` y disco persistente montado en `/var/data`.
   - **Static Site** `bolus-ai-frontend` que ejecuta `npm ci && npm run build` en `frontend/` y publica `frontend/dist`.
2. Variables de entorno recomendadas:
   - `JWT_SECRET` (obligatoria, marcar como *Sync: false* en Render).
   - `DATA_DIR=/var/data` (ya definido en `render.yaml`).
   - `NIGHTSCOUT_URL` (opcional, si conectas con Nightscout).
   - `VITE_API_BASE_URL` en el Static Site (Render la rellenará automáticamente con la URL del backend gracias a `render.yaml`; si falla, asígnala manualmente a la URL HTTPS del backend).
3. HTTPS es obligatorio: usa siempre la URL `https://...onrender.com` al configurar el frontend y Nightscout.

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
