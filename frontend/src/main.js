// Main Entry Point
import { initRouter, registerView, registerDefaultView, router } from './modules/core/router.js';

// Views
import { renderBasal } from './modules/views/basal.js';
import { renderScan } from './modules/views/bolus.js';
import { renderPatterns } from './modules/views/patterns.js';
import { renderSuggestions } from './modules/views/suggestions.js';
import { renderLogin, renderChangePassword } from './modules/views/auth.js';

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
registerView('#/scan', renderScan);
registerView('#/bolus', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('bolus'));
});
registerView('#/basal', renderBasal);

// Analysis & History
registerView('#/history', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => {
    mountReactPage('history');
  });
});
registerView('#/patterns', renderPatterns);
registerView('#/suggestions', renderSuggestions);

// Configuration & Auth
registerView('#/settings', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => {
    mountReactPage('settings');
  });
});
registerView('#/login', renderLogin);
registerView('#/change-password', renderChangePassword);

// Hybrid React Pages
registerView('#/favorites', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => {
    mountReactPage('favorites');
  });
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
