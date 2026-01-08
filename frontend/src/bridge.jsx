import React from 'react';
import ReactDOM from 'react-dom/client';
import { ToastContainer } from './components/ui/Toast';

import { RESTAURANT_MODE_ENABLED } from './lib/featureFlags';
import { DraftNotification } from './components/layout/DraftNotification';

const PAGE_LOADERS = {
    favorites: () => import('./pages/FavoritesPage'),
    history: () => import('./pages/HistoryPage'),
    settings: () => import('./pages/SettingsPage'),
    home: () => import('./pages/HomePage'),
    bolus: () => import('./pages/BolusPage'),
    scan: () => import('./pages/ScanPage'),
    basal: () => import('./pages/BasalPage'),
    patterns: () => import('./pages/PatternsPage'),
    'nightscout-settings': () => import('./pages/NightscoutSettingsPage'),
    login: () => import('./pages/LoginPage'),
    'change-password': () => import('./pages/ChangePasswordPage'),
    suggestions: () => import('./pages/SuggestionsPage'),
    profile: () => import('./pages/ProfilePage'),
    menu: () => import('./pages/MenuPage'),
    scale: () => import('./pages/ScalePage'),
    'food-db': () => import('./pages/FoodDatabasePage'),
    bodymap: () => import('./pages/BodyMapPage'),
    supplies: () => import('./pages/SuppliesPage'),
    notifications: () => import('./pages/NotificationsPage'),
    forecast: () => import('./pages/ForecastPage'),
    status: () => import('./pages/StatusPage'),
    manual: () => import('./pages/ManualCalculatorPage'),
};

if (RESTAURANT_MODE_ENABLED) {
    PAGE_LOADERS.restaurant = () => import('./pages/RestaurantPage');
}

let reactRoot = null;
let mountToken = 0;

async function loadPageComponent(pageName) {
    const loader = PAGE_LOADERS[pageName];
    if (!loader) return null;
    const module = await loader();
    return module.default;
}

export async function mountReactPage(pageName, containerId = 'app') {
    const token = ++mountToken;
    const container = document.getElementById(containerId);
    if (!container) return;

    // Clear any vanilla content (innerHTML) EXCEPT if it's already our React root?
    // Actually, vanilla router does app.innerHTML = '' before calling render.
    // So container is empty.

    // Problem: If we keep creating roots, React warns.
    // We should reuse root if possible. But vanilla router destroys the DOM node content.
    // So the previous root is effectively detached/dead if we used 'innerHTML=""'.

    // React 18: createRoot(container).
    // If we call createRoot on a container that has been cleared by innerHTML="", it's fine, it's a new root.

    // However, if we want to share the root persistence, we should probably have a dedicated
    // <div id="react-root"></div> inside #app?
    // Let's stick to simple: Mount new root. It's safe enough for page transitions.

    container.innerHTML = '<div class="spinner">Cargando...</div>';
    let Component = null;
    try {
        Component = await loadPageComponent(pageName);
    } catch (error) {
        console.error("React page load error:", error);
        if (token !== mountToken) return;
        container.innerHTML = `<div class="error">React Load Error: ${error.message}</div>`;
        return;
    }
    if (token !== mountToken) return;
    if (!Component) {
        container.innerHTML = `<div class="error">React Component '${pageName}' not found</div>`;
        return;
    }

    try {
        if (reactRoot) {
            reactRoot.unmount();
            reactRoot = null;
        }

        // Optional: clear container if unmount didn't fully clean up (React usually does)
        container.innerHTML = '';

        reactRoot = ReactDOM.createRoot(container);
        reactRoot.render(
            <React.StrictMode>
                <Component />
                <DraftNotification />
                <ToastContainer />
            </React.StrictMode>
        );
    } catch (e) {
        console.error("React Mount Error:", e);
        container.innerHTML = `<div class="error">React Crash: ${e.message}</div>`;
    }
}
