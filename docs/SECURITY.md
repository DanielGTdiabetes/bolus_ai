# Seguridad

## Decisiones
- Autenticación con usuario/contraseña usando bcrypt para almacenar `password_hash`.
- Emisión de JWT HS256 con `access` (15m) y `refresh` (7d). El `issuer` es configurable.
- El backend almacena los hashes de refresh tokens en `backend/data/sessions.json` para permitir invalidación de sesiones.
- Los ajustes y otros datos se persisten en archivos JSON dentro de `DATA_DIR` (por defecto `data/`).
- Endpoints críticos (`/api/settings`, `/api/changes`, `/api/bolus/recommend`, Nightscout) requieren autenticación, y `PUT /api/settings` exige rol `admin`.

## Almacenamiento
- Usuarios: `backend/data/users.json` con `username`, `password_hash`, `role`, `created_at`, `needs_password_change`.
- Sesiones: `backend/data/sessions.json` con hash de refresh y estado de revocación.
- Ajustes: `backend/data/settings.json` con migración automática a partir de valores por defecto.

## Recomendaciones de despliegue
- Configura `JWT_SECRET` con un valor fuerte y único en producción.
- Usa HTTPS terminando en Nginx o en el propio entorno para proteger tokens en tránsito.
- Define orígenes CORS explícitos (`CORS_ORIGINS`) en producción.
- Protege los archivos de datos (`DATA_DIR`) con permisos restringidos si se despliega en host tradicional.
