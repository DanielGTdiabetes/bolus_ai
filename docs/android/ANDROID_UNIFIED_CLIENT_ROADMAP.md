# Bolus AI Android Unified Client

## Alcance

La rama `codex/android-unified-client` transforma Companion en la aplicación
Android principal sin sustituir el frontend web ni mover el cálculo clínico
fuera del backend.

Prioridades:

1. Interfaz móvil cuidada con Jetpack Compose y sistema visual propio.
2. MyFitnessPal, Health Connect, Dexcom y cola offline integrados.
3. Selección NAS/Render mediante comprobación de salud.
4. Cámara, galería y báscula como flujos móviles integrados.
5. Secretos almacenados mediante Android Keystore.
6. Backend Bolus AI como fuente de verdad para cálculos completos.

La navegación Android debe exponer todas las rutas funcionales del frontend actual.
Durante la migración, estas rutas se abrirán usando el frontend compartido y el
servidor saludable. Las funciones específicas de Android permanecerán nativas:
MyFitnessPal, Health Connect, Dexcom, cola local, permisos y diagnóstico.

## Wear OS

Wear OS se desarrollará como una aplicación independiente en una fase posterior.
No se implementará en esta rama conexión Bluetooth directa con Dexcom G7.

La futura app del reloj podrá obtener lecturas mediante:

- sincronización con la aplicación Android del teléfono;
- API de Bolus AI;
- Nightscout, cuando se configure como fuente.

La aplicación móvil no dependerá de que la aplicación Wear OS exista.

## Límites de seguridad

- La calculadora offline móvil seguirá identificándose como limitada.
- La aplicación no activará automáticamente `EMERGENCY_MODE` en Render.
- Un cambio NAS/Render no interrumpirá una operación de bolo iniciada.
- Una lectura antigua o sin fuente verificable nunca se presentará como actual.
- La interfaz no duplicará la lógica clínica del backend.
