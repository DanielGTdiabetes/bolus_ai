# Bolus AI

Monorepo con backend FastAPI y frontend React/Vite.

## Variables de entorno
- `JWT_SECRET` (obligatoria)
- `JWT_ISSUER` (opcional)
- `NIGHTSCOUT_URL` (opcional)
- `DATA_DIR` (opcional)

## Usuarios
Al iniciar por primera vez se crea `backend/data/users.json` con un usuario admin (`admin` / `admin123`) marcado como `needs_password_change`. Inicia sesión y usa un endpoint futuro de gestión o edita el archivo para cambiar la contraseña generando un nuevo `password_hash` (bcrypt).

## Ejecución local
```
pip install -r backend/requirements.txt
export JWT_SECRET=changeme
uvicorn backend.app.main:app --reload
```

Frontend:
```
cd frontend
npm install
npm run dev
```

## Docker
```
docker-compose up --build
```

## Tests
```
pytest backend/tests
```
