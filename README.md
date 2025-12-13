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
