# NAS Docker Deploy (MVP)

Este despliegue usa PostgreSQL local en el NAS y el backend de FastAPI sirviendo el frontend estático ya incluido en `backend/app/static`.

## Requisitos

- Docker y Docker Compose instalados en el NAS.
- Acceso a la carpeta del repo en el NAS.

## Pasos de instalación

1. En el NAS, copia el archivo de variables de entorno:

   ```bash
   cp .env.example .env
   ```

2. Ajusta los valores en `.env` (al menos `POSTGRES_PASSWORD`, `JWT_SECRET` y `APP_SECRET_KEY`).

3. Levanta los servicios:

   ```bash
   docker compose up -d --build
   ```

4. Revisa logs del backend (útil para diagnósticos):

   ```bash
   docker compose logs -f --tail=200 backend
   ```

## Verificación rápida

- Health check del backend:

  ```bash
  curl -sS http://<NAS_IP>:<PORT>/api/health
  ```

  - Reemplaza `<PORT>` por `NAS_PORT` (por defecto `8000`).

- Frontend:
  - Abre en el navegador `http://<NAS_IP>:<PORT>/` y verifica que cargue y permita login.

## Notas

- No se configura aún sincronización NAS↔Neon. Cuando se implemente, se añadirá aquí sin alterar este MVP.
