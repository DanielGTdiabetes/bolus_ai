// Main Entry Point
import { initRouter, registerView, registerDefaultView, router } from './modules/core/router.js';
import { cleanupLegacyFrontendState, installChunkRecovery } from './modules/core/frontendRecovery.js';

installChunkRecovery();

registerView('#/supplies', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('supplies'));
});

import { RESTAURANT_MODE_ENABLED } from './lib/featureFlags';

registerDefaultView(() => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('home'));
});

registerView('#/', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('home'));
});
registerView('#/home', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('home'));
});
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
registerView('#/history', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('history'));
});
registerView('#/notifications', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('notifications'));
});
registerView('#/learning', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('learning'));
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
registerView('#/favorites', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('favorites'));
});

if (RESTAURANT_MODE_ENABLED) {
  registerView('#/restaurant', () => {
    import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('restaurant'));
  });
}

registerView('#/manual', () => {
  import('./bridge.jsx').then(({ mountReactPage }) => mountReactPage('manual'));
});

initRouter();

document.addEventListener('DOMContentLoaded', async () => {
  await cleanupLegacyFrontendState();

  const { checkBackendHealth, syncSettings, validateStoredSession } = await import('./modules/core/store.js');
  await validateStoredSession();
  checkBackendHealth();
  syncSettings();

  router();
});
