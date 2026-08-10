// Legacy service-worker kill switch.
//
// Bolus AI no longer uses a service worker for frontend asset caching because
// cache-first handling of Vite's hashed lazy chunks can mix two deployments.
// Keeping this file lets browsers that still have an older worker registered
// receive one final update that clears Bolus AI caches and unregisters itself.

const LEGACY_CACHE_PREFIX = 'bolus-ai-';

self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(Promise.resolve());
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        try {
            const cacheNames = await caches.keys();
            await Promise.all(
                cacheNames
                    .filter((name) => name.startsWith(LEGACY_CACHE_PREFIX))
                    .map((name) => caches.delete(name)),
            );
        } catch (error) {
            console.warn('Could not clear legacy Bolus AI caches.', error);
        }

        try {
            await self.registration.unregister();
        } catch (error) {
            console.warn('Could not unregister legacy Bolus AI service worker.', error);
        }

        try {
            const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
            for (const client of clients) {
                client.postMessage({ type: 'BOLUS_AI_LEGACY_SW_REMOVED' });
            }
        } catch (error) {
            console.warn('Could not notify clients about service worker cleanup.', error);
        }
    })());
});

// Never intercept requests. Network responses always win while this worker is
// waiting to be replaced/removed.
self.addEventListener('fetch', () => {});
