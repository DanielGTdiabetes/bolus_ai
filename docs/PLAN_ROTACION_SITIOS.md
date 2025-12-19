# 📍 Plan de Implementación: Rotación de Sitios de Inyección

## Objetivo
Ayudar al usuario a recordar dónde se inyectó por última vez y sugerir la siguiente zona para evitar lipodistrofias.

## Lógica Personalizada
Según tus preferencias:
*   **Bolo (Comida/Rápida):** Zonas prioritarias -> Abdomen (Estómago).
*   **Basal (Lenta):** Zonas prioritarias -> Piernas (Muslos) y Glúteos.

## 1. Nuevo Componente: `<InjectionSiteSelector />`
Crearemos un componente visual interactivo.
*   **Interfaz:** No usaremos una lista de texto aburrida. Usaremos una representación esquemática simple (o botones grandes claros) dividida en cuadrantes.
    *   **Abdomen:** `Sup. Izq`, `Sup. Der`, `Inf. Izq`, `Inf. Der`.
    *   **Piernas:** `Muslo Izq`, `Muslo Der`.
    *   **Glúteos:** `Izq`, `Der`.
*   **Feedback Visual:**
    *   🔴 **Rojo:** Última zona usada (Evitar).
    *   🟢 **Verde:** Zona recomendada (Sugerencia de rotación).

## 2. Integración en `BolusPage.jsx` (Rápida)
*   Añadir el selector en la pantalla de confirmación ("ResultView").
*   Filtrar para mostrar principalmente las zonas de **Abdomen** (con opción de "ver otras" si un día quieres cambiar).
*   Guardar la zona elegida en las `notes` de Nightscout (ej: `[Abdomen-Der]`) para tener registro histórico.

## 3. Integración en `BasalPage.jsx` (Lenta)
*   Añadir el selector al registrar la dosis.
*   Filtrar para mostrar **Piernas y Glúteos**.
*   Lógica de rotación específica para basal (que suele ser cada 24h).

## 4. Persistencia
*   Usaremos `localStorage` para recordar la *última* inyección inmediatamente.
*   (Futuro) Analizar el historial de Nightscout para reconstruir el historial si cambias de móvil.

## ¿Empezamos?
Paso 1: Crear el componente visual.
Paso 2: Conectarlo a la página de Bolus.
