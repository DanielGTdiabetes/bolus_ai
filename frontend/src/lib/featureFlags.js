const flagFromEnv = (import.meta?.env?.VITE_RESTAURANT_MODE_ENABLED ?? 'false').toString().toLowerCase();
export const RESTAURANT_MODE_ENABLED = flagFromEnv === 'true' || flagFromEnv === '1';

export const RESTAURANT_CORRECTION_CARBS = Number(import.meta?.env?.VITE_RESTAURANT_CORRECTION_CARBS || 12);
