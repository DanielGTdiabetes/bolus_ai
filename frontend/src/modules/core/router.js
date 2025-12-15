import { state } from './store.js';
import { setUnauthorizedHandler, logout } from '../../lib/api.js';

// Route Handlers (These will be set by main.js to avoid circular imports during refactor)
// Once all views are modularized, we can import them here or in a routes config.
let viewRegistry = {};

export function registerView(route, handler) {
    viewRegistry[route] = handler;
}

export function registerDefaultView(handler) {
    viewRegistry['*'] = handler;
}

export function navigate(hash) {
    window.location.hash = hash;
}

export function ensureAuthenticated() {
    if (!state.token) {
        navigate('#/login');
        return false;
    }
    return true;
}

export function redirectToLogin() {
    navigate("#/login");
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
    const handler = viewRegistry[route];
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
    setUnauthorizedHandler(() => {
        state.token = null;
        state.user = null;
        redirectToLogin();
        router(); // Re-render logic
    });

    // Listen
    window.addEventListener("hashchange", () => router());

    // Initial Call
    // router(); // Let main.js bootstrap this
    routerInitialized = true;
}
