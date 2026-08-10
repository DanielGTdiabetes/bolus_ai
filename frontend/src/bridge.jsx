import React from 'react';
import ReactDOM from 'react-dom/client';
import { ToastContainer } from './components/ui/Toast';
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

let reactRoot = null;
let reactContainer = null;
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
            await new Promise((resolve) => setTimeout(resolve, 500));
            return loadPageComponent(pageName, retries - 1);
        }
        return { Component: null, error };
    }
}

function ensureReactRoot(container) {
    if (reactRoot && reactContainer === container) {
        return reactRoot;
    }

    if (reactRoot) {
        try {
            reactRoot.unmount();
        } catch (error) {
            console.warn('Could not unmount previous React root cleanly.', error);
        }
    }

    container.replaceChildren();
    reactRoot = ReactDOM.createRoot(container);
    reactContainer = container;
    return reactRoot;
}

function PageLoading({ pageName }) {
    return (
        <div className="spinner" role="status" aria-live="polite">
            Cargando {pageName}...
        </div>
    );
}

function PageLoadFallback({ pageName, error, onRetry }) {
    const message = error?.message || 'No se pudo cargar esta pantalla.';

    return (
        <div className="error" style={{ padding: '1.5rem', textAlign: 'center' }}>
            <div style={{ fontSize: '1.2rem', marginBottom: '0.5rem' }}>
                ⚠️ Error cargando {pageName}
            </div>
            <div style={{ color: '#64748b', marginBottom: '1rem' }}>{message}</div>
            <button
                type="button"
                onClick={onRetry}
                style={{
                    background: '#3b82f6',
                    color: 'white',
                    border: 'none',
                    padding: '0.6rem 1rem',
                    borderRadius: '8px',
                    cursor: 'pointer',
                }}
            >
                Reintentar
            </button>
        </div>
    );
}

export async function mountReactPage(pageName, containerId = 'app') {
    const token = ++mountToken;
    const container = document.getElementById(containerId);
    if (!container) return;

    const root = ensureReactRoot(container);
    root.render(<PageLoading pageName={pageName} />);

    const { Component, error: loadError } = await loadPageComponent(pageName);
    if (token !== mountToken) return;

    if (loadError) {
        console.error('React page load error:', loadError);
        root.render(
            <PageLoadFallback
                pageName={pageName}
                error={loadError}
                onRetry={() => mountReactPage(pageName, containerId)}
            />
        );
        return;
    }

    if (!Component) {
        root.render(
            <PageLoadFallback
                pageName={pageName}
                error={new Error(`Componente '${pageName}' no encontrado`)}
                onRetry={() => mountReactPage(pageName, containerId)}
            />
        );
        return;
    }

    try {
        root.render(
            <React.StrictMode>
                <ErrorBoundary
                    key={pageName}
                    onRetry={() => mountReactPage(pageName, containerId)}
                >
                    <Component />
                    <ToastContainer />
                </ErrorBoundary>
            </React.StrictMode>
        );
    } catch (error) {
        console.error('React Mount Error:', error);
        root.render(
            <PageLoadFallback
                pageName={pageName}
                error={error}
                onRetry={() => mountReactPage(pageName, containerId)}
            />
        );
    }
}
