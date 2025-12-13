# Seguridad

- Autenticación con JWT (access 15m, refresh 7d) firmados con `JWT_SECRET`.
- Refresh tokens almacenados como hash en `backend/data/sessions.json` y revocables en logout.
- Passwords guardadas con bcrypt en `backend/data/users.json`.
- Endpoints sensibles requieren autenticación; ajustes requieren rol admin.
- Configurar CORS con orígenes permitidos (`CORS_ORIGINS`).
- Despliegue recomendado siempre tras un proxy HTTPS; mantener `JWT_SECRET` seguro.
