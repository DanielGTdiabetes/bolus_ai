// Main Entry Point
import { initRouter, registerView, registerDefaultView, router } from './modules/core/router.js';

registerView('#/supplies', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('supplies'));
});

// Settings & Profile imported directly, all lazy via bridge!

// Register Routes
// The Router in this project uses the full hash string as the key.
// Settings & Profile imported directly, all lazy via bridge!

import { RESTAURANT_MODE_ENABLED } from './lib/featureFlags';


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
registerView('#/notifications', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('notifications'));
});
registerView('#/patterns', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('patterns'));
});
registerView('#/suggestions', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('suggestions'));
});
registerView('#/forecast', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('forecast'));
});
registerView('#/status', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('status'));
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

if (RESTAURANT_MODE_ENABLED) {
  registerView('#/restaurant', () => {
    import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('restaurant'));
  });
}

// Emergency Manual Mode
registerView('#/manual', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('manual'));
});

// Initialize Router
initRouter();

// Trigger Initial Render
document.addEventListener('DOMContentLoaded', async () => {
  // Check backend health (DB mode)
  import('./modules/core/store.js').then(({ checkBackendHealth, syncSettings }) => {
    checkBackendHealth();
    syncSettings();
  });

  router();

  // Register NEW Service Worker (v3) for PWA
  // EMERGENCY: Disable Service Workers to fix caching issues
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations().then(registrations => {
      for (let registration of registrations) {
        console.log("Force Unregistering SW to fix cache:", registration);
        registration.unregister();
      }
    });
  }
});
