// Main Entry Point
import { initRouter, registerView, registerDefaultView, router } from './modules/core/router.js';

// Views - None imported directly, all lazy via bridge!

// Register Routes
// The Router in this project uses the full hash string as the key.
import './bridge.jsx'; // Ensure bridge is loaded for side effects or types if needed, though we import dynamically below.
import { setUnauthorizedHandler } from './lib/api';
import { RESTAURANT_MODE_ENABLED } from './lib/featureFlags';

setUnauthorizedHandler(() => {
  window.location.hash = '#/login';
});

registerDefaultView(() => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('home'));
});

// Home
registerView('#/', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('home'));
});
registerView('#/home', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('home'));
});

// Core Features
registerView('#/scan', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('scan'));
});
registerView('#/bolus', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('bolus'));
});
registerView('#/basal', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('basal'));
});
registerView('#/scale', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('scale'));
});
registerView('#/food-db', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('food-db'));
});

// Analysis & History
registerView('#/history', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('history'));
});
registerView('#/patterns', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('patterns'));
});
registerView('#/suggestions', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('suggestions'));
});

// Configuration & Auth
registerView('#/settings', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('settings'));
});
registerView('#/nightscout-settings', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('nightscout-settings'));
});
registerView('#/login', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('login'));
});
registerView('#/change-password', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('change-password'));
});
registerView('#/profile', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('profile'));
});
registerView('#/menu', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('menu'));
});
registerView('#/bodymap', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('bodymap'));
});

// Hybrid React Pages
registerView('#/favorites', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('favorites'));
});

registerView('#/restaurant', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('restaurant'));
});

// Initialize Router
initRouter();

// Trigger Initial Render
document.addEventListener('DOMContentLoaded', async () => {
  // Check backend health (DB mode)
  import('./modules/core/store.js').then(({ checkBackendHealth }) => checkBackendHealth());

  router();

  // Register Service Worker for PWA
  if ('serviceWorker' in navigator) {
    try {
      const reg = await navigator.serviceWorker.register('./sw.js');
      console.log('SW Registered:', reg.scope);
    } catch (err) {
      console.log('SW Registration failed:', err);
    }
  }
});
