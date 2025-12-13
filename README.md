# Bolus AI

Esqueleto inicial para una aplicación web (PWA en el futuro) con backend FastAPI y preparación para frontend vía Nginx.

## Estructura

```
bolus-ai/
  backend/
    app/
      api/
      core/
      models/
      services/
    tests/
    Dockerfile
    requirements.txt
    pyproject.toml
  config/
    config.example.json
    nginx.conf
  docker-compose.yml
  README.md
```

## Configuración

1. Copia el archivo de ejemplo y ajusta los valores según tu Nightscout:
   ```bash
   cp config/config.example.json config/config.json
   ```

2. Variables de entorno soportadas (se priorizan sobre el archivo de configuración):
   - `NIGHTSCOUT_BASE_URL`
   - `NIGHTSCOUT_API_SECRET`
   - `NIGHTSCOUT_TOKEN`
   - `CONFIG_PATH` (ruta al `config.json` si no usas la ubicación por defecto)
   - `SERVER_HOST`, `SERVER_PORT`, `NIGHTSCOUT_TIMEOUT_SECONDS`

### Autenticación Nightscout

- Si tu instancia usa token, se enviará como `Authorization: Bearer <token>`.
- Si usa `api-secret`, se aplica `SHA1` al secreto plano y se envía en el header `API-SECRET`, que es el mecanismo habitual de Nightscout. Algunas instancias pueden requerir el secreto sin hash; en ese caso, coloca el hash o desactiva el secreto en la configuración y habilita el token.

## Ejecución con Docker Compose

```bash
cp config/config.example.json config/config.json
# opcional: crear .env para variables adicionales
cd /workspace/bolus_ai
docker compose up --build
```

- Backend disponible en `http://localhost:8000`.
- Nginx de placeholder expone `http://localhost:8080` y proxya `/api/` hacia el backend.

## Endpoints

- `GET /api/health` → `{ "ok": true }`
- `GET /api/health/full` → incluye uptime, versión, estado Nightscout y configuración pública del servidor.
- `GET /api/nightscout/status`
- `GET /api/nightscout/sgv/latest`
- `GET /api/nightscout/treatments/recent?hours=24`

### Ejemplos con curl

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/health/full
curl http://localhost:8000/api/nightscout/status
curl http://localhost:8000/api/nightscout/sgv/latest
curl "http://localhost:8000/api/nightscout/treatments/recent?hours=12"
```

## Desarrollo local (sin Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Pruebas

```bash
cd backend
pytest -q
```

## Notas de diseño

- La configuración se carga primero desde variables de entorno y luego se rellenan valores faltantes con `config/config.json`.
- Cliente Nightscout usa `httpx.AsyncClient` con timeouts configurables y logs estructurados.
- Los tests usan `respx` para simular las respuestas de Nightscout.
