import { getStoredToken, getStoredUser, getSettings, putSettings, importSettings } from '../../lib/api';

// Keys
const CALC_PARAMS_KEY = "bolusai_calc_params";
const LEGACY_CALC_SETTINGS_KEY = "bolusai_calc_settings";
const SPLIT_SETTINGS_KEY = "bolusai_split_settings";
const SETTINGS_VERSION_KEY = "bolusai_settings_version";
const DUAL_PLAN_KEY = "bolusai_active_dual_plan";

// Main Global State
export const state = {
    token: getStoredToken(),
    user: getStoredUser(),
    settingsSynced: false,
    loadingUser: false,

    // Bolus Calc State
    bolusResult: null,
    bolusError: "",

    // Health & Hardware
    dbMode: "sql",
    healthStatus: "Pulsa el botón para comprobar.",
    scale: {
        connected: false,
        grams: 0,
        stable: false,
        battery: null,
        status: "Desconectado"
    },
    visionResult: null,
    visionError: null,

    // Glucose
    currentGlucose: {
        loading: false,
        data: null, // { bg_mgdl, trend, age, stale, ok, error }
        timestamp: 0
    },

    // Plans
    activeDualPlan: null,
    activeDualTimer: null,

    // UI Modes
    calcMode: "meal",

    // Plate Builder
    plateWeightGrams: null,
    plateBuilder: {
        entries: [],
        carbs_total: 0,
        mode_weight: "single", // "single" | "incremental"
        weight_base_grams: 0,
        base_history: [],
    },

    // Raw Scale Data
    scaleReading: {
        grams: null,
        stable: false,
        battery: null,
        lastUpdateTs: 0,
        window: [] // [{ts, grams}]
    },

    // Notifications
    notifications: {
        hasUnread: false,
        items: []
    }
};

// --- Settings Logic ---

export function getCalcParams() {
    try {
        const raw = localStorage.getItem(CALC_PARAMS_KEY);
        if (raw) return JSON.parse(raw);

        // Fallback Legacy
        const legacy = localStorage.getItem(LEGACY_CALC_SETTINGS_KEY);
        if (legacy) {
            console.log("Migrating legacy calc settings...");
            const parsed = JSON.parse(legacy);
            saveCalcParams(parsed); // Migrate
            return parsed;
        }
        return null;
    } catch (e) {
        return null;
    }
}

export function saveCalcParams(params, skipSync = false) {
    localStorage.setItem(CALC_PARAMS_KEY, JSON.stringify(params));

    // Emit event for local components
    if (!skipSync) {
        window.dispatchEvent(new CustomEvent('bolusai-settings-changed', { detail: params }));
    }

    // Trigger backend sync
    if (!skipSync && state.user) {
        triggerBackendSave(params);
    }
}

export function getSettingsVersion() {
    return parseInt(localStorage.getItem(SETTINGS_VERSION_KEY) || "0", 10);
}

export function saveSettingsVersion(v) {
    localStorage.setItem(SETTINGS_VERSION_KEY, String(v));
}

export function getSplitSettings() {
    try {
        const raw = localStorage.getItem(SPLIT_SETTINGS_KEY);
        return raw ? JSON.parse(raw) : {
            enabled_default: false,
            percent_now: 70,
            duration_min: 120,
            later_after_min: 120,
            round_step_u: 0.5
        };
    } catch (e) {
        return {
            enabled_default: false,
            percent_now: 70,
            duration_min: 120,
            later_after_min: 120,
            round_step_u: 0.5
        };
    }
}

export function saveSplitSettings(settings) {
    localStorage.setItem(SPLIT_SETTINGS_KEY, JSON.stringify(settings));
}

export function getDefaultMealParams(calcParams) {
    return calcParams?.lunch ?? null;
}

// --- Sync Logic ---

export async function syncSettings() {
    if (!state.user) return;

    const local = getCalcParams();

    try {
        const serverRes = await getSettings();
        const serverSettings = serverRes.settings;
        const serverVersion = serverRes.version;

        if (serverSettings) {
            saveCalcParams(serverSettings, true);
            saveSettingsVersion(serverVersion);
            console.log("Settings synced from server (v" + serverVersion + ")");
        } else if (local) {
            console.log("Importing local settings to server...");
            const importRes = await importSettings(local);
            saveSettingsVersion(importRes.version);
            if (importRes.imported) console.log("Settings imported.");
        }
    } catch (e) {
        console.error("Sync failed:", e);
    }
}

export async function checkBackendHealth() {
    // Dynamic import to avoid circular dependency if api depends on store (not the case here, but good practice if needed)
    // Actually api.js is already imported.
    const { fetchHealth } = await import('../../lib/api.js');
    try {
        const health = await fetchHealth();
        if (health && health.database && health.database.mode === "memory") {
            state.dbMode = "memory";
            console.warn("⚠️ Backend running in IN-MEMORY mode. Data is volatile.");
        } else {
            state.dbMode = "sql";
        }
    } catch (e) {
        console.error("Health check failed:", e);
    }

    // Auto-Run Night Scan if missed (Lazy Execution for Free Tier)
    const todayStr = new Date().toISOString().slice(0, 10);
    const lastScan = localStorage.getItem("bolusai_last_autoscan");

    if (lastScan !== todayStr && state.user && state.user.role === 'admin') {
        console.log("Checking scheduled tasks (lazy run)...");
        try {
            const { runAutoScan } = await import('../../lib/api.js');
            await runAutoScan();
            localStorage.setItem("bolusai_last_autoscan", todayStr);
            console.log("Lazy autoscan triggered successfully.");
        } catch (e) {
            console.warn("Lazy autoscan failed:", e);
        }
    }
}

async function triggerBackendSave(params) {
    const version = getSettingsVersion();
    try {
        const res = await putSettings(params, version);
        saveSettingsVersion(res.version);
        console.log("Settings saved to backend (v" + res.version + ")");
    } catch (e) {
        if (e.isConflict) {
            handleSettingsConflict(e, params);
        } else {
            console.error("Save settings error:", e);
        }
    }
}

function handleSettingsConflict(errorData, localParams) {
    const modal = document.createElement('dialog');
    modal.style = "border:none; border-radius:12px; padding:2rem; box-shadow:0 25px 50px -12px rgba(0,0,0,0.25); max-width:400px";
    modal.innerHTML = `
      <h3 style="margin-top:0">Conflicto de sincronización</h3>
      <p>Se han detectado cambios en otro dispositivo (v${errorData.serverVersion}).</p>
      <div style="display:flex; flex-direction:column; gap:0.5rem; margin-top:1rem;">
        <button id="btn-use-server" style="background:var(--primary); color:white; border:none; padding:10px; border-radius:8px; cursor:pointer;">Usar servidor (recomendado)</button>
        <button id="btn-overwrite" style="background:#e2e8f0; color:#334155; border:none; padding:10px; border-radius:8px; cursor:pointer;">Sobrescribir servidor</button>
      </div>
    `;
    document.body.appendChild(modal);
    modal.showModal();

    document.getElementById('btn-use-server').onclick = () => {
        saveCalcParams(errorData.serverSettings, true);
        saveSettingsVersion(errorData.serverVersion);
        modal.close();
        document.body.removeChild(modal);
        alert("Configuración actualizada desde el servidor.");
        // Force refresh if needed
        window.location.reload();
    };

    document.getElementById('btn-overwrite').onclick = async () => {
        try {
            const res = await putSettings(localParams, errorData.serverVersion);
            saveSettingsVersion(res.version);
            modal.close();
            document.body.removeChild(modal);
            alert("Servidor sobrescrito.");
        } catch (e) {
            modal.close();
            document.body.removeChild(modal);
            alert("Error al sobrescribir: " + e.message);
        }
    };
}


// --- Dual Plan Store ---

export function getDualPlan() {
    try {
        const raw = localStorage.getItem(DUAL_PLAN_KEY);
        if (!raw) return null;
        const plan = JSON.parse(raw);
        if (Date.now() - plan.created_at_ts > 6 * 60 * 60 * 1000) {
            localStorage.removeItem(DUAL_PLAN_KEY);
            return null;
        }
        return plan;
    } catch (e) { return null; }
}

export function saveDualPlan(plan) {
    state.activeDualPlan = plan;
    localStorage.setItem(DUAL_PLAN_KEY, JSON.stringify(plan));
}

export function getDualPlanTiming(plan) {
    if (!plan) return null;
    const now = Date.now();
    const elapsed_ms = now - plan.created_at_ts;
    const elapsed_min = Math.floor(elapsed_ms / 60000);
    const duration_min = plan.extended_duration_min || plan.later_after_min || 120;

    // If we use 'later_after_min' as target time for second dose
    // Remaining = duration - elapsed
    const remaining_min = Math.max(0, duration_min - elapsed_min);

    return { elapsed_min, remaining_min, duration_min };
}
