import assert from 'node:assert/strict';
import {
    cleanupLegacyFrontendState,
    installChunkRecovery,
    markChunkRecovery,
    shouldRecoverFromChunkError,
} from '../src/modules/core/frontendRecovery.js';

function makeStorage() {
    const values = new Map();
    return {
        getItem(key) {
            return values.has(key) ? values.get(key) : null;
        },
        setItem(key, value) {
            values.set(key, String(value));
        },
    };
}

{
    const storage = makeStorage();
    assert.equal(shouldRecoverFromChunkError(storage, 10_000), true);
    markChunkRecovery(storage, 10_000);
    assert.equal(shouldRecoverFromChunkError(storage, 20_000), false);
    assert.equal(shouldRecoverFromChunkError(storage, 40_000), true);
}

{
    const deletedCaches = [];
    let unregisterCount = 0;
    const navigatorObj = {
        serviceWorker: {
            async getRegistrations() {
                return [
                    { async unregister() { unregisterCount += 1; return true; } },
                    { async unregister() { unregisterCount += 1; return true; } },
                ];
            },
        },
    };
    const cachesObj = {
        async keys() {
            return ['bolus-ai-v2', 'bolus-ai-v3', 'another-app-cache'];
        },
        async delete(name) {
            deletedCaches.push(name);
            return true;
        },
    };

    await cleanupLegacyFrontendState({ navigatorObj, cachesObj });
    assert.equal(unregisterCount, 2);
    assert.deepEqual(deletedCaches.sort(), ['bolus-ai-v2', 'bolus-ai-v3']);
}

{
    const listeners = new Map();
    const storage = makeStorage();
    let reloadCount = 0;
    let preventDefaultCount = 0;

    const windowObj = {
        sessionStorage: storage,
        location: { reload() { reloadCount += 1; } },
        setTimeout(callback) { callback(); },
        addEventListener(type, callback) { listeners.set(type, callback); },
        removeEventListener(type) { listeners.delete(type); },
    };

    const uninstall = installChunkRecovery({ windowObj });
    const handler = listeners.get('vite:preloadError');
    assert.equal(typeof handler, 'function');

    handler({
        preventDefault() { preventDefaultCount += 1; },
        payload: new Error('Failed to fetch dynamically imported module'),
    });

    assert.equal(preventDefaultCount, 1);
    assert.equal(reloadCount, 1);

    // A second immediate error must not create a reload loop.
    handler({ preventDefault() { preventDefaultCount += 1; } });
    assert.equal(preventDefaultCount, 2);
    assert.equal(reloadCount, 1);

    uninstall();
    assert.equal(listeners.has('vite:preloadError'), false);
}

console.log('Frontend recovery tests passed.');
