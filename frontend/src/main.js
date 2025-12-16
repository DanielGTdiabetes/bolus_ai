// Main Entry Point
import { initRouter, registerView, registerDefaultView, router } from './modules/core/router.js';

// Views
import { renderHome } from './modules/views/home.js';
import { renderBasal } from './modules/views/basal.js';
import { renderScan, renderBolus } from './modules/views/bolus.js'; // Note: bolus.js exports both
import { renderHistory } from './modules/views/history.js';
import { renderPatterns } from './modules/views/patterns.js';
import { renderSuggestions } from './modules/views/suggestions.js';
import { renderSettings } from './modules/views/settings.js';
import { renderLogin, renderChangePassword } from './modules/views/auth.js';

// Register Routes
// The Router in this project uses the full hash string as the key.
registerDefaultView(renderHome);

// Home
registerView('#/', renderHome);
registerView('#/home', renderHome);

// Core Features
registerView('#/scan', renderScan);
registerView('#/bolus', renderBolus);
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
registerView('#/settings', renderSettings);
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
