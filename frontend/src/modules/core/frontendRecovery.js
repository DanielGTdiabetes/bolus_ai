const CHUNK_RECOVERY_KEY = 'bolus-ai:chunk-recovery-at';
const CHUNK_RECOVERY_COOLDOWN_MS = 30_000;
const LEGACY_CACHE_PREFIX = 'bolus-ai-';

function readRecoveryTimestamp(storage) {
    if (!storage) return 0;
    try {
        const value = Number(storage.getItem(CHUNK_RECOVERY_KEY));
        return Number.isFinite(value) ? value : 0;
    } catch {
        return 0;
    }
}

export function shouldRecoverFromChunkError(storage, now = Date.now()) {
    const lastRecoveryAt = readRecoveryTimestamp(storage);
    return !lastRecoveryAt || now - lastRecoveryAt >= CHUNK_RECOVERY_COOLDOWN_MS;
}

export function markChunkRecovery(storage, now = Date.now()) {
    if (!storage) return;
    try {
        storage.setItem(CHUNK_RECOVERY_KEY, String(now));
    } catch {
        // Storage can be unavailable in hardened/private browser contexts.
    }
}

export function installChunkRecovery({ windowObj = globalThis.window } = {}) {
    if (!windowObj?.addEventListener) return () => {};

    const onPreloadError = (event) => {
        // Vite dispatches this event when a hashed lazy-loaded chunk is missing.
        // Prevent the default throw so we can recover with one controlled reload.
        event?.preventDefault?.();

        const storage = windowObj.sessionStorage;
        const now = Date.now();
        if (!shouldRecoverFromChunkError(storage, now)) {
            console.error('Dynamic chunk recovery suppressed to avoid a reload loop.', event?.payload || event);
            return;
        }

        markChunkRecovery(storage, now);
        console.warn('Detected stale frontend assets. Reloading once to use the current build.');

        const reload = () => windowObj.location?.reload?.();
        if (typeof windowObj.setTimeout === 'function') {
            windowObj.setTimeout(reload, 0);
        } else {
            reload();
        }
    };

    windowObj.addEventListener('vite:preloadError', onPreloadError);
    return () => windowObj.removeEventListener?.('vite:preloadError', onPreloadError);
}

export async function cleanupLegacyFrontendState({
    navigatorObj = globalThis.navigator,
    cachesObj = globalThis.caches,
} = {}) {
    const tasks = [];

    if (navigatorObj?.serviceWorker?.getRegistrations) {
        tasks.push((async () => {
            try {
                const registrations = await navigatorObj.serviceWorker.getRegistrations();
                await Promise.all(registrations.map(async (registration) => {
                    try {
                        await registration.unregister();
                    } catch (error) {
                        console.warn('Could not unregister legacy service worker.', error);
                    }
                }));
            } catch (error) {
                console.warn('Could not inspect service worker registrations.', error);
            }
        })());
    }

    if (cachesObj?.keys) {
        tasks.push((async () => {
            try {
                const cacheNames = await cachesObj.keys();
                const legacyCaches = cacheNames.filter((name) => name.startsWith(LEGACY_CACHE_PREFIX));
                await Promise.all(legacyCaches.map(async (name) => {
                    try {
                        await cachesObj.delete(name);
                    } catch (error) {
                        console.warn(`Could not delete legacy cache ${name}.`, error);
                    }
                }));
            } catch (error) {
                console.warn('Could not inspect browser caches.', error);
            }
        })());
    }

    await Promise.all(tasks);
}
