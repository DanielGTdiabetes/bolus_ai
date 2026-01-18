# Guía de Migraciones en Render para Bolus AI

## Problema Detectado
Errores de esquema en producción indican que las tablas de la base de datos no se crearon o actualizaron correctamente.

## Solución Implementada
Hemos automatizado la ejecución de migraciones usando Alembic antes de arrancar la aplicación.

### 1. Script de Inicio (`backend/start.sh`)
Se ha creado un script idempotente que:
1.  Ejecuta `alembic upgrade head` para aplicar migraciones pendientes.
2.  Inicia el servidor `uvicorn`.

### 2. Dockerfile Actualizado
El `Dockerfile` ahora copia y ejecuta `start.sh` en lugar de ejecutar `uvicorn` directamente. Esto garantiza que **cada despliegue** verifique el esquema de la DB.

## Instrucciones para Render (Docker)
Si estás desplegando vía Docker (recomendado):
- No es necesario cambiar nada en la configuración de Render.
- El nuevo `CMD` en el `Dockerfile` se encarga de todo.
- Asegúrate de limpiar la caché de build si es posible ("Clear Build Cache & Deploy") para asegurar que se copien los nuevos scripts.

## Instrucciones para Render (Nativo / Python Environment)
Si NO usas Docker y usas el entorno nativo de Python en Render:
1.  Ve a **Settings** de tu servicio en Render.
2.  En **Build Command**, asegúrate de instalar las dependencias: `pip install -r backend/requirements.txt`.
3.  En **Pre-Deploy Command** (muy importante), añade:
    ```bash
    cd backend && alembic upgrade head
    ```
    *Nota: Render ejecuta esto antes de arrancar la nueva versión.*
4.  En **Start Command**, mantén: `uvicorn app.main:app ...`

## Verificación de Salud
Revisa los logs de arranque para confirmar que las migraciones se aplicaron sin errores y que la aplicación inicia sin fallos de esquema.
