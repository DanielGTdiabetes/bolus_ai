# Guía de Solución de Problemas: Menús Faltantes en NAS

## 🔍 Diagnóstico de la Simulación

He realizado una simulación "estática" del proceso de construcción del contenedor para identificar por qué faltan los menús.

**Resultado de la Simulación:**

1. **Código Fuente (`SettingsPage.jsx`):** ✅ **CORRECTO**.
    - El archivo contiene explícitamente los nuevos menús: "CÁLCULO V3", "IA / Visión", "Aprendizaje (ML)".
2. **Configuración de Rutas (`Dockerfile`):** ✅ **CORRECTO**.
    - La etapa 1 copia correctamente `frontend/` y construye en `dist`.
    - La etapa 2 copia correctamente `dist` a `/app/app/static`.
    - El backend (`main.py`) sirve correctamente desde `/app/app/static`.
3. **Causa del Fallo:** ❌ **ERROR DE CACHÉ DOCKER**.
    - Docker en el NAS está reutilizando una capa de construcción antigua ("cached").
    - Aunque tienes el código nuevo, Docker cree que nada ha cambiado y usa la versión compilada anterior.

## 🛠️ Solución (Cómo forzar la actualización)

Tienes dos opciones para solucionar esto en el NAS:

### Opción A: Reconstrucción Forzada (Recomendada)

Si usas Portainer o Terminal, ejecuta este comando para forzar la invalidación completa de la caché y reconstruir la App:

```bash
# 1. Navega a la carpeta de despliegue (ajusta la ruta según tu NAS)
cd /ruta/a/bolus_ai/deploy/nas

# 2. Fuerza la reconstrucción sin caché
docker-compose build --no-cache app

# 3. Levanta de nuevo el servicio
docker-compose up -d --force-recreate app
```

### Opción B: Actualización vía Portainer

Si solo usas la interfaz web de Portainer:

1. Ve a tu **Stack** o **Service**.
2. Busca la opción **"Repull image"** (aunque aquí construimos localmente, a veces ayuda si usas imagen).
3. **MEJOR:** He actualizado el archivo `Dockerfile` con una variable `ENV BUILD_DATE="...-V4-FORCE"`.
    - Simplemente **Haz un "Pull" del repositorio Git** en Portainer.
    - Dale a **"Update the stack"** (asegúrate de marcar "Re-pull image" o "Re-build").
    - El cambio en esa línea obligará a Docker a recompilar el frontend.

## 🧪 Verificación

Una vez reconstruido, entra en la App y verifica que aparecen las pestañas:

- Nightscout
- Dexcom
- **CÁLCULO V3** (Nueva)
- **IA / Visión** (Nueva)
