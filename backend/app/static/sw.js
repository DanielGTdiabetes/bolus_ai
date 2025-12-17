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
    // Network first, fall back to cache strategy for API calls often works better 
    // but for static assets cache first is faster.
    // For simplicity: Stale-While-Revalidate or Network First for API.

    if (e.request.url.includes('/api/')) {
        // API: Network only (or fallback if you want offline read-only)
        return;
    }

    e.respondWith(
        caches.match(e.request).then((response) => {
            return response || fetch(e.request);
        })
    );
});
