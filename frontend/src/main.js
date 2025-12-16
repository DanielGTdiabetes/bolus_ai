// Main Entry Point
import { initRouter, registerView, registerDefaultView, router } from './modules/core/router.js';

// Views - None imported directly, all lazy via bridge!

// Register Routes
// The Router in this project uses the full hash string as the key.
import './bridge.jsx'; // Ensure bridge is loaded for side effects or types if needed, though we import dynamically below.
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
registerView('#/login', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('login'));
});
registerView('#/change-password', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('change-password'));
});

// Hybrid React Pages
registerView('#/favorites', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('favorites'));
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
