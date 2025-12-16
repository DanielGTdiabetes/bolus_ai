import { useSyncExternalStore } from 'react';
import { state, subscribe, getSnapshot } from '../modules/core/store.js';

/**
 * Hook to access the legacy global store in React.
 * @param {Function} [selector] - Optional selector function (s) => s.prop
 * @returns {any} The selected state
 */
export function useStore(selector = (s) => s) {
    // Subscribe to version changes
    useSyncExternalStore(subscribe, getSnapshot);

    // Return selected state
    // Note: Since 'state' is mutable, we rely on the version bump to force re-render.
    return selector(state);
}
