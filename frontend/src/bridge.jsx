import React from 'react';
import ReactDOM from 'react-dom/client';
import NightscoutSettingsPage from './pages/NightscoutSettingsPage';

// Registry of React Pages
import FavoritesPage from './pages/FavoritesPage';
import HistoryPage from './pages/HistoryPage';
import SettingsPage from './pages/SettingsPage';
import HomePage from './pages/HomePage';
import BolusPage from './pages/BolusPage';
import ScanPage from './pages/ScanPage';
import BasalPage from './pages/BasalPage';
import PatternsPage from './pages/PatternsPage';
import SuggestionsPage from './pages/SuggestionsPage';
import LoginPage from './pages/LoginPage';
import ChangePasswordPage from './pages/ChangePasswordPage';
import ProfilePage from './pages/ProfilePage';
import { RESTAURANT_MODE_ENABLED } from './lib/featureFlags';
import RestaurantPage from './pages/RestaurantPage';
import MenuPage from './pages/MenuPage';
import FoodDatabasePage from './pages/FoodDatabasePage';
import ScalePage from './pages/ScalePage';

const PAGES = {
    'favorites': FavoritesPage,
    'history': HistoryPage,
    'settings': SettingsPage,
    'home': HomePage,
    'bolus': BolusPage,
    'scan': ScanPage,
    'basal': BasalPage,
    'patterns': PatternsPage,
    'nightscout-settings': NightscoutSettingsPage,
    'login': LoginPage,
    'change-password': ChangePasswordPage,
    'suggestions': SuggestionsPage,
    'profile': ProfilePage,
    'menu': MenuPage,
    'scale': ScalePage,
    'food-db': FoodDatabasePage,
};

if (RESTAURANT_MODE_ENABLED) {
    PAGES['restaurant'] = RestaurantPage;
}

let reactRoot = null;

export function mountReactPage(pageName, containerId = 'app') {
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

    const Component = PAGES[pageName];
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
            </React.StrictMode>
        );
    } catch (e) {
        console.error("React Mount Error:", e);
        container.innerHTML = `<div class="error">React Crash: ${e.message}</div>`;
    }
}
