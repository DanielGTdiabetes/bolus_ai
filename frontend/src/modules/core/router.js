import { state } from './store.js';
import { logout } from '../../lib/api.js';
import { navigate, redirectToLogin } from './navigation.js';

// Route Handlers (These will be set by main.js to avoid circular imports during refactor)
// Once all views are modularized, we can import them here or in a routes config.
let viewRegistry = {};

export function registerView(route, handler) {
    viewRegistry[route] = handler;
}

export function registerDefaultView(handler) {
    viewRegistry['*'] = handler;
}

export function ensureAuthenticated() {
    if (!state.token) {
        navigate('#/login');
        return false;
    }
    return true;
}

let routerInitialized = false;

export async function router() {
    const route = window.location.hash || "#/";

    // Auth Guard
    if (!state.user && route !== "#/login") {
        // We can't use viewRegistry['#/login'] directly if not registered yet?
        // Assume login is registered.
        const loginHandler = viewRegistry['#/login'];
        if (loginHandler) loginHandler();
        return;
    }

    // Route Matching
    // Strip query params for matching (e.g. #/suggestions?tab=accepted -> #/suggestions)
    const baseRoute = route.split('?')[0];
    const handler = viewRegistry[baseRoute];
    if (handler) {
        await handler();
    } else {
        // Default
        const defaultHandler = viewRegistry['*'];
        if (defaultHandler) await defaultHandler();
    }

    // Global Hooks (e.g. Notifications)
    if (state.user && window.checkNotifications && route !== "#/login") {
        window.checkNotifications();
    }
}

export function initRouter() {
    if (routerInitialized) return;

    // Expose global for legacy calls
    window.navigate = navigate;
    window.logout = logout; // Ensuring logout is globally available if used in HTML

    // Auth Handler
    // Auth Handler via Events (Decoupled)
    window.addEventListener('auth:logout', (event) => {
        // Force cleanup and redirect always
        state.token = null;
        state.user = null;
        try {
            localStorage.clear(); // Ensure clean slate
            sessionStorage.clear();
        } catch (e) { }

        redirectToLogin();
        // Force reload if needed to clear React state, but try router() first
        router();
    });

    // Listen
    window.addEventListener("hashchange", () => router());

    // Initial Call
    // router(); // Let main.js bootstrap this
    routerInitialized = true;
}
