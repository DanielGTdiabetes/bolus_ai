# Plan de Refactorización Modular del Frontend (Bolus AI)

Estado actual: Vanilla JavasScript con manipulación manual del DOM (`innerHTML`).
Objetivo: Migrar progresivamente a **React** manteniendo la funcionalidad actual y mejorando la mantenibilidad.

---

## 📅 Fase 1: Preparación del Entorno (Inmediato)
- [ ] **Instalación de Dependencias**:
    - `npm install react react-dom wouter` (Wouter es un router ultra-ligero ideal para esto).
    - `npm install -D @types/react @types/react-dom @vitejs/plugin-react`.
- [ ] **Configuración de Vite**:
    - Modificar `vite.config.js` para incluir el plugin de React.
    - Renombrar `main.js` a `main.jsx` (o `.tsx` si nos animamos a TS estricto).

## 🏗️ Fase 2: Arquitectura Híbrida (Coexistencia)
*Objetivo: Que React funcione dentro de la app actual sin romper nada.*
- [ ] Crear carpeta `src/components/` y `src/pages/`.
- [ ] Crear un componente "Contenedor" en React que se monte en el `div#app`.
- [ ] **Router Híbrido**:
    - Mantener el router actual (`hashchange`) por ahora.
    - Crear un componente React `<BridgeView />` que detecte en qué ruta estamos y decida si renderizar un componente React o dejar que el sistema legacy pinte el HTML.

## 🧱 Fase 3: Migración de Componentes "Átomos"
Refactorizar primero las piezas pequeñas que se usan en todas partes.
- [ ] **Botones e Inputs**: `Button`, `Input`, `Card`.
- [ ] **Layout**: `Header`, `BottomNav` (ahora son strings, pasarlos a componentes JSX).
- [ ] **Global Store**: Conectar el estado global (`store.js`) a React.
    - Crear un hook `useStore()` que se suscriba a los cambios de `store.js` para que los componentes reaccionen solos.

## 🚀 Fase 4: Migración de Pantallas (Por Prioridad)
1.  **Configuración (`Settings`)**: Es la más aislada y formulario-intensiva. Perfecta para empezar.
2.  **Home (`Dashboard`)**: Requiere conexión en tiempo real. Buen test para hooks.
3.  **Historial (`History`)**: Listado simple, fácil de migrar.
4.  **Calculadora (`Bolus`)**: **La más crítica**. Se deja para el final cuando tengamos dominada la arquitectura.

## 🧹 Fase 5: Limpieza
- [ ] Eliminar archivos `.js` antiguos de la carpeta `modules/views`.
- [ ] Eliminar lógica manual de eventos (`document.getElementById...`).
- [ ] Unificar estilos CSS en módulos o Styled Components (opcional, por ahora `style.css` global vale).

---

## 📝 Notas Técnicas
*   **Estado Global**: Mantendremos `store.js` como fuente de la verdad por ahora, pero lo envolveremos en `useSyncExternalStore` (hook de React) para que sea reactivo.
*   **Estilos**: Seguiremos usando el `style.css` actual para no perder tiempo re-estilizando. React usará `className` en lugar de `class`.
