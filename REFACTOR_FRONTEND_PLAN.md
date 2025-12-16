# Plan de Refactorización Modular del Frontend (Bolus AI)

Estado actual: Vanilla JavasScript con manipulación manual del DOM (`innerHTML`).
Objetivo: Migrar progresivamente a **React** manteniendo la funcionalidad actual y mejorando la mantenibilidad.

---

## 📅 Fase 1: Preparación del Entorno (Inmediato)
- [x] **Instalación de Dependencias**:
    - `npm install react react-dom wouter` (Wouter es un router ultra-ligero ideal para esto).
    - `npm install -D @types/react @types/react-dom @vitejs/plugin-react`.
- [x] **Configuración de Vite**:
    - Modificar `vite.config.js` para incluir el plugin de React.
    - Renombrar `main.js` a `main.jsx` (o `.tsx` si nos animamos a TS estricto) -> *Nota: Mantenemos main.js pero importamos bridge.jsx*.

## 🏗️ Fase 2: Arquitectura Híbrida (Coexistencia)
*Objetivo: Que React funcione dentro de la app actual sin romper nada.*
- [x] Crear carpeta `src/components/` y `src/pages/`.
- [x] Crear un componente "Contenedor" en React que se monte en el `div#app`.
- [x] **Router Híbrido**:
    - Mantener el router actual (`hashchange`) por ahora.
    - Crear un componente React `<BridgeView />` (`bridge.jsx`) que detecte en qué ruta estamos y decida si renderizar un componente React o dejar que el sistema legacy pinte el HTML.

## 🧱 Fase 3: Migración de Componentes "Átomos"
Refactorizar primero las piezas pequeñas que se usan en todas partes.
- [x] **Botones e Inputs**: `Button`, `Input`, `Card` (Creados en `Atoms.jsx`).
- [x] **Layout**: `Header`, `BottomNav` (ahora son componentes JSX).
- [x] **Global Store**: Conectar el estado global (`store.js`) a React.
    - [x] Crear un hook `useStore()` que se suscriba a los cambios de `store.js` para que los componentes reaccionen solos.

## 🚀 Fase 4: Migración de Pantallas (Por Prioridad)
1.  **Historial (`History`)**: [x] COMPLETADA. Migrado a React (`HistoryPage.jsx`).
2.  **Configuración (`Settings`)**: [x] COMPLETADA (`SettingsPage.jsx`).
3.  **Home (`Dashboard`)**: [x] COMPLETADA. Migrada a React (`HomePage.jsx`) con auto-refresh cada 60s.
4.  **Calculadora (`Bolus`)**: [x] COMPLETADA. Migrado a `BolusPage.jsx` con lógica completa.

## 🧹 Fase 5: Limpieza
- [x] Eliminar archivos `.js` antiguos de la carpeta `modules/views` (TODOS ELIMINADOS).
- [x] Eliminar referencias en `main.js`.
- [x] Verificar que no queda código muerto crítico.
- [x] Eliminar lógica manual de eventos (`document.getElementById...`).
- [ ] Unificar estilos CSS en módulos o Styled Components (opcional, por ahora `style.css` global vale).

## ✅ ESTADO FINAL
- Migración 100% completada a React.
- Backend robusto (Neon DB + Local Backup + Nightscout).
- Frontend rápido y modular.
- Código limpio y sin dependencias circulares vanilla.

## 📝 Notas Técnicas
*   **Estado Global**: Mantendremos `store.js` como fuente de la verdad por ahora, pero lo envolveremos en `useSyncExternalStore` (hook de React) para que sea reactivo.
*   **Estilos**: Seguiremos usando el `style.css` actual para no perder tiempo re-estilizando. React usará `className` en lugar de `class`.
