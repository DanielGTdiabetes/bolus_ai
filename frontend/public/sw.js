// sw.js - Service Worker for caching app shell
const CACHE_NAME = 'bolus-ai-v1';
const ASSETS = [
    './',
    './index.html',
    './src/style.css',
    './src/main.js',
    './manifest.json'
];

self.addEventListener('install', (e) => {
    e.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS);
        })
    );
});

self.addEventListener('fetch', (e) => {
    // 1. API: Network Only (Never cache, always needs live data or fails)
    if (e.request.url.includes('/api/')) {
        return;
    }

    // 2. Assets (JS, CSS, Images, HTML): Stale-While-Revalidate / Cache First with update
    // This ensures that if the user visits the page, we save the chunks for offline usage automatically
    // regardless of their hashed filenames.
    e.respondWith(
        caches.match(e.request).then((cachedResponse) => {
            // Strategy: Return cached if found, BUT also fetch update in background (if we wanted strict SWR)
            // Simpler for stability: Cache First, falling back to network, and caching that network response.

            if (cachedResponse) {
                return cachedResponse;
            }

            return fetch(e.request).then((networkResponse) => {
                // Check if valid response
                if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
                    return networkResponse;
                }

                // Cache it for future offline access
                const responseToCache = networkResponse.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(e.request, responseToCache);
                });

                return networkResponse;
            }).catch(() => {
                // If offline and not in cache, we could return a fallback.html, but usually SPA index.html is enough
                // if we visited it before.
            });
        })
    );
});
