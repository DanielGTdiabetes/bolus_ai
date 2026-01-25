import React from 'react';
import ReactDOM from 'react-dom/client';
import { ToastContainer } from './components/ui/Toast';
import { RESTAURANT_MODE_ENABLED } from './lib/featureFlags';

import { ErrorBoundary } from './components/ui/ErrorBoundary';

const PAGE_LOADERS = {
    favorites: () => import('./pages/FavoritesPage'),
    history: () => import('./pages/HistoryPage'),
    settings: () => import('./pages/SettingsPage'),
    home: () => import('./pages/HomePage'),
    bolus: () => import('./pages/BolusPage'),
    scan: () => import('./pages/ScanPage'),
    basal: () => import('./pages/BasalPage'),
    learning: () => import('./pages/LearningPage'),
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

async function loadPageComponent(pageName, retries = 1) {
    const loader = PAGE_LOADERS[pageName];
    if (!loader) return { Component: null, error: null };
    try {
        const module = await loader();
        return { Component: module.default, error: null };
    } catch (error) {
        if (retries > 0) {
            console.warn(`Retrying load for ${pageName}...`);
            await new Promise(r => setTimeout(r, 500));
            return loadPageComponent(pageName, retries - 1);
        }
        return { Component: null, error };
    }
}

function renderPageFallback(container, pageName, error, containerId) {
    const message = error?.message ? `${error.message}` : 'No se pudo cargar esta pantalla.';
    container.innerHTML = `
        <div class="error" style="padding: 1.5rem; text-align: center;">
            <div style="font-size: 1.2rem; margin-bottom: 0.5rem;">⚠️ Error cargando ${pageName}</div>
            <div style="color: #64748b; margin-bottom: 1rem;">${message}</div>
            <button id="retry-react-page" style="background:#3b82f6;color:white;border:none;padding:0.6rem 1rem;border-radius:8px;cursor:pointer;">
                Reintentar
            </button>
        </div>
    `;
    const retryButton = container.querySelector('#retry-react-page');
    if (retryButton) {
        retryButton.addEventListener('click', () => mountReactPage(pageName, containerId));
    }
}

export async function mountReactPage(pageName, containerId = 'app') {
    const token = ++mountToken;
    const container = document.getElementById(containerId);
    if (!container) return;

    // OPTIMIZATION: Check if we are mounting into the same container that already has React.
    // If so, do NOT clear innerHTML = 'Loading'. Just Render.
    // However, we must ensure we are the owners.

    // We only show spinner if we don't have a root or if the token is old (force refresh)
    // But for spa navigation, we want instant feel.

    // Pre-load component BEFORE touching DOM if possible
    const { Component, error: loadError } = await loadPageComponent(pageName);

    if (token !== mountToken) return; // Discard if another nav happened

    if (loadError) {
        console.error("React page load error:", loadError);
        container.innerHTML = ''; // Now we can clear
        renderPageFallback(container, pageName, loadError, containerId);
        return;
    }

    if (!Component) {
        container.innerHTML = '';
        renderPageFallback(container, pageName, new Error(`Componente '${pageName}' no encontrado`), containerId);
        return;
    }

    try {
        // If root exists and container is still valid, reuse it
        if (!reactRoot) {
            container.innerHTML = ''; // Start clean
            reactRoot = ReactDOM.createRoot(container);
        } else {
            // Check if container is the same? 
            // In this architecture, container is usually always 'app'.
            // But if vanilla router wiped it, reactRoot._internalRoot may be detached.

            // Heuristic: If container is empty, our root is dead.
            if (!container.hasChildNodes()) {
                reactRoot = ReactDOM.createRoot(container);
            }
        }

        reactRoot.render(
            <React.StrictMode>
                <ErrorBoundary onRetry={() => mountReactPage(pageName, containerId)}>
                    <Component />

                    <ToastContainer />
                </ErrorBoundary>
            </React.StrictMode>
        );
    } catch (e) {
        console.error("React Mount Error:", e);
        container.innerHTML = `<div class="error">React Crash: ${e.message}</div>`;
        reactRoot = null;
    }
}
