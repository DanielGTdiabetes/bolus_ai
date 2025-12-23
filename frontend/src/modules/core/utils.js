import { state } from './store';

// Helper to format Trend
export function formatTrend(trend, stale) {
    if (stale) return "⚠️";
    const icons = {
        "DoubleUp": "↑↑",
        "SingleUp": "↑",
        "FortyFiveUp": "↗",
        "Flat": "→",
        "FortyFiveDown": "↘",
        "SingleDown": "↓",
        "DoubleDown": "↓↓"
    };
    return icons[trend] || trend || "";
}

// --- SCALER HELPER WITH DERIVED STABILITY ---
export function getDerivedStability() {
    const w = state.scaleReading?.window || [];
    if (w.length < 3) return { derivedStable: false, delta: null };
    const grams = w.map(p => p.grams);
    const delta = Math.max(...grams) - Math.min(...grams);
    // Stable if variation <= 2g in the window
    return { derivedStable: delta <= 2, delta };
}

export function getPlateBuilderReading() {
    const r = state.scaleReading || {};
    const { derivedStable, delta } = getDerivedStability();

    return {
        grams: typeof r.grams === "number" ? r.grams : null,
        stable: derivedStable, // OVERRIDE stable flag
        battery: r.battery ?? null,
        ageMs: r.lastUpdateTs ? (Date.now() - r.lastUpdateTs) : null,
        delta: delta,
        connected: state.scale.connected
    };
}

export function getScaleReading() {
    return getPlateBuilderReading();
}

export function getDualPlanTiming(plan) {
    if (!plan?.created_at_ts || !plan?.later_after_min) return null;
    const elapsed_min = Math.floor((Date.now() - plan.created_at_ts) / 60000);
    const duration = plan.extended_duration_min || plan.later_after_min;
    const remaining_min = Math.max(0, duration - elapsed_min);
    return { elapsed_min, remaining_min };
}

export function formatNotes(notes) {
    if (!notes) return "";
    // Remove brackets around "Sitio: ..." and replace with neat bullet
    return notes.replace(/\[Sitio: (.*?)\]/g, "• Sitio: $1");
}
