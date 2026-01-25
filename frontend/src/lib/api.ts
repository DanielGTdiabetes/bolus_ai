import { createApiFetch } from "./apiClientCore";

function normalizeBaseUrl(value?: string | null) {
  return value ? String(value).replace(/\/$/, "") : null;
}

const DEFAULT_API_BASE = "/api";

export function getApiBase() {
  const envBase =
    normalizeBaseUrl(import.meta.env?.VITE_API_BASE_URL) ||
    normalizeBaseUrl(import.meta.env?.VITE_API_URL);
  if (envBase) return envBase;

  return DEFAULT_API_BASE;
}

const API_BASE = getApiBase();
const TOKEN_KEY = "auth_token";
const LEGACY_TOKEN_KEYS = ["bolusai_token", "token"];
const USER_KEY = "bolusai_user";
const NS_STORAGE_KEY = "bolusai_ns_config"; // Legacy (localStorage)
const NS_SESSION_KEY = "bolusai_ns_config_session";

// Unauthorized handler removed. API only emits events.

// Helper: NS Config Local
function migrateLegacyNsConfig() {
  try {
    const legacy = localStorage.getItem(NS_STORAGE_KEY);
    if (legacy) {
      sessionStorage.setItem(NS_SESSION_KEY, legacy);
      localStorage.removeItem(NS_STORAGE_KEY);
    }
  } catch (e) {
    console.warn("NS config migration failed", e);
  }
}

migrateLegacyNsConfig();

export function getLocalNsConfig() {
  try {
    const raw = sessionStorage.getItem(NS_SESSION_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e) {
    console.warn("Failed to read session NS config", e);
  }
  try {
    // Legacy fallback (should be removed after migration)
    const legacy = localStorage.getItem(NS_STORAGE_KEY);
    return legacy ? JSON.parse(legacy) : null;
  } catch (e) {
    return null;
  }
}

export function saveLocalNsConfig(config) {
  sessionStorage.setItem(NS_SESSION_KEY, JSON.stringify(config));
  localStorage.removeItem(NS_STORAGE_KEY);
}

export async function migrateNsSecretToBackend() {
  const cfg = getLocalNsConfig();
  if (!cfg || !cfg.url || !cfg.token) return;
  try {
    await saveNightscoutSecret({ url: cfg.url, api_secret: cfg.token, enabled: true });
    sessionStorage.removeItem(NS_SESSION_KEY);
  } catch (e) {
    console.warn("No se pudo guardar el secreto Nightscout en backend (se mantendrá en sesión).", e?.message || e);
  }
}

// ... rest of the file ... (I'll copy existing)

export function getStoredToken() {
  const existing = localStorage.getItem(TOKEN_KEY);
  if (existing) return existing;
  for (const legacyKey of LEGACY_TOKEN_KEYS) {
    const legacyToken = localStorage.getItem(legacyKey);
    if (legacyToken) {
      localStorage.setItem(TOKEN_KEY, legacyToken);
      localStorage.removeItem(legacyKey);
      return legacyToken;
    }
  }
  return null;
}

export function getStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

export function saveSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function isAuthenticated() {
  return Boolean(getStoredToken());
}

export async function toJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return {};
  }
}

interface ApiOptions extends RequestInit {
  headers?: Record<string, string>;
}

const PUBLIC_ENDPOINTS = ["/api/auth/login"];

function isPublicEndpoint(path: string) {
  return PUBLIC_ENDPOINTS.some((endpoint) => path.startsWith(endpoint));
}

function notifyAuthLogout(reason: string) {
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    try {
      window.dispatchEvent(new CustomEvent("auth:logout", { detail: { reason } }));
    } catch (error) {
      console.warn("Failed to dispatch auth:logout event", error);
    }
  }
}

export function resolveApiUrl(path: string) {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const base = API_BASE || "";
  if (typeof window === "undefined") return path;
  if (!base) return new URL(path, window.location.origin).toString();
  const baseUrl = base.startsWith("http") ? base : new URL(base, window.location.origin).toString();
  return new URL(path, baseUrl).toString();
}

export const apiFetch = createApiFetch({
  fetchImpl: fetch,
  getToken: () => getStoredToken(),
  clearToken: () => clearSession(),
  onLogout: () => notifyAuthLogout("unauthorized"),
  resolveUrl: resolveApiUrl,
  isPublicEndpoint,
  isDev: Boolean(import.meta.env?.DEV),
  onMissingToken: () => notifyAuthLogout("missing_token"),
});

export async function loginRequest(username, password) {
  const response = await apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  const data = await toJson(response);
  if (!response.ok) {
    throw new Error(data.detail || "Credenciales inválidas");
  }
  if (!data.access_token) {
    throw new Error("Respuesta de login inválida (sin access_token).");
  }
  saveSession(data.access_token, data.user);
  return data;
}

export async function fetchMe() {
  const response = await apiFetch("/api/auth/me");
  const data = await toJson(response);
  if (!response.ok) {
    throw new Error(data.detail || "No se pudo cargar el usuario");
  }
  return data;
}

export async function changePassword(old_password, new_password) {
  const response = await apiFetch("/api/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ old_password, new_password }),
  });
  const data = await toJson(response);
  if (!response.ok) {
    throw new Error(data.detail || "No se pudo actualizar la contraseña");
  }
  if (data.user) {
    saveSession(getStoredToken(), data.user);
  }
  return data;
}

export async function updateProfile(new_username, password) {
  const response = await apiFetch("/api/auth/change-profile", {
    method: "POST",
    body: JSON.stringify({ new_username, password }),
  });
  const data = await toJson(response);
  if (!response.ok) {
    throw new Error(data.detail || "Error al actualizar perfil");
  }
  if (data.user && data.access_token) {
    saveSession(data.access_token, data.user);
  }
  return data;
}

export async function calculateBolus(payload) {
  const response = await apiFetch("/api/bolus/calc", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const data = await toJson(response);
  if (!response.ok) {
    const detailObj = typeof data.detail === "object" ? data.detail : null;
    const detail = detailObj?.message || data.detail || data.message || "No se pudo calcular";
    const err: any = new Error(detail);
    err.payload = detailObj || data;
    err.error_code = detailObj?.error_code || data.error_code;
    err.status = response.status;
    throw err;
  }
  return data;
}

export async function fetchHealth() {
  if (!getStoredToken()) {
    throw new Error("Sesión caducada. Vuelve a iniciar sesión.");
  }
  const response = await apiFetch("/api/health/full");
  const data = await toJson(response);
  if (!response.ok) {
    throw new Error(data.detail || "No se pudo verificar la salud del backend");
  }
  return data;
}

export async function getNightscoutStatus() {
  const response = await apiFetch("/api/nightscout/status");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener estado Nightscout");
  return data;
}

export async function getCurrentGlucose(config) {
  if (isAuthenticated()) {
    const response = await apiFetch("/api/nightscout/current", {
      method: "GET"
    });
    const data = await toJson(response);
    if (!response.ok) throw new Error(data.detail || "Error al obtener glucosa (Backend)");
    return data;
  }
  // If config is present, use stateless POST
  if (config && config.url) {
    const response = await apiFetch("/api/nightscout/current", {
      method: "POST",
      body: JSON.stringify(config)
    });
    const data = await toJson(response);
    if (!response.ok) throw new Error(data.detail || "Error al obtener glucosa");
    return data;
  } else {
    // Fallback to server-stored GET
    const response = await apiFetch("/api/nightscout/current", {
      method: "GET"
    });
    const data = await toJson(response);
    if (!response.ok) throw new Error(data.detail || "Error al obtener glucosa (Backend)");
    return data;
  }
}

export async function getGlucoseEntries(count = 36) { // 36 * 5 min = 3 hours
  const safeCount = count || 36;
  const response = await apiFetch(`/api/nightscout/entries?count=${safeCount}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener historial glucosa");
  return data;
}

export async function testNightscout(config) {
  const body = config ? JSON.stringify(config) : undefined;
  const response = await apiFetch("/api/nightscout/test", {
    method: "POST",
    body,
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || data.message || "Error al probar conexión");
  return data;
}

export async function getNightscoutSecretStatus() {
  const response = await apiFetch("/api/nightscout/secret");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error checkeando secretos");
  return data;
}

export async function saveNightscoutSecret(payload) {
  // payload: {url, api_secret, enabled}
  const response = await apiFetch("/api/nightscout/secret", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error guardando secretos");
  return data;
}

export async function deleteNightscoutSecret() {
  const response = await apiFetch("/api/nightscout/secret", {
    method: "DELETE"
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error eliminando secretos");
  return data;
}

interface VisionOptions {
  meal_slot?: string;
  bg_mgdl?: number;
  target_mgdl?: number;
  portion_hint?: string;
  prefer_extended?: boolean;
  plate_weight_grams?: number;
  nightscout?: { url?: string; token?: string };
  round_step_u?: number;
  existing_items?: string;
  image_description?: string;
  signal?: AbortSignal;
}

export async function estimateCarbsFromImage(file: File, options: VisionOptions = {}) {
  const formData = new FormData();
  formData.append("image", file);
  if (options.meal_slot) formData.append("meal_slot", options.meal_slot);
  if (options.bg_mgdl) formData.append("bg_mgdl", String(options.bg_mgdl));
  if (options.target_mgdl) formData.append("target_mgdl", String(options.target_mgdl));
  if (options.portion_hint) formData.append("portion_hint", options.portion_hint);
  if (options.image_description) formData.append("image_description", options.image_description);

  if (typeof options.prefer_extended !== 'undefined') formData.append("prefer_extended", String(options.prefer_extended));

  if (options.plate_weight_grams) {
    formData.append("plate_weight_grams", String(options.plate_weight_grams));
  }

  if (options.nightscout) {
    if (options.nightscout.url) formData.append("nightscout_url", options.nightscout.url);
    if (options.nightscout.token) formData.append("nightscout_token", options.nightscout.token);
  }

  if (typeof options.round_step_u !== 'undefined') {
    formData.append("round_step_u", String(options.round_step_u));
  }

  if (options.existing_items) {
    formData.append("existing_items", options.existing_items);
  }

  // Use raw fetch for FormData to avoid Content-Type issue
  const token = getStoredToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(resolveApiUrl("/api/vision/estimate"), {
    method: "POST",
    headers,
    body: formData,
    signal: options.signal,
  });

  const data = await toJson(response);
  if (!response.ok) {
    if (response.status === 401) {
      logout();
      throw new Error("Sesión caducada");
    }
    throw new Error(data.detail || "Error al analizar imagen");
  }
  return data;
}

export async function getIOBData(config) {
  // Config (local mode) is legacy but kept for compatibility.
  // Ideally, backend handles NS connection.
  let url = "/api/bolus/iob";
  // We do NOT send token/url in params if we can avoid it.
  // Assuming Backend has secrets. If config is passed, it might be for overrides,
  // but we strip sensitive info if needed.
  // For now, removing params to satisfy "no token in URL".
  // If the backend needs dynamic context, it should likely be POST or use headers,
  // but standard flow is: Backend uses stored secrets.
  const response = await apiFetch(url);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener IOB");
  return data;
}

export async function saveTreatment(payload) {
  const response = await apiFetch("/api/bolus/treatments", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al guardar tratamiento");
  return data;
}

export async function fetchTreatments(config) {
  // Similar to IOB, we remove explicit token passing in URL.
  let url = "/api/nightscout/treatments";
  const params = new URLSearchParams();

  // If count is specified, pass it.
  if (config && config.count) {
    params.append("count", String(config.count));
  }
  if (config && config.from_date) {
    params.append("from_date", config.from_date);
  }
  if (config && config.to_date) {
    params.append("to_date", config.to_date);
  }
  // We purposefully ignore config.url/token here to avoid leaking secrets in URL.
  // The backend must rely on its stored configuration.

  if (params.toString()) {
    url += "?" + params.toString();
  }

  const response = await apiFetch(url);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener tratamientos");
  return data;
}

export async function fetchRecentNutritionImports(limit = 10) {
  const params = new URLSearchParams();
  if (limit) {
    params.append("limit", String(limit));
  }
  const url = params.toString()
    ? `/api/integrations/nutrition/recent?${params.toString()}`
    : "/api/integrations/nutrition/recent";
  const response = await apiFetch(url);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener importaciones");
  return data;
}

export async function createBolusPlan(payload) {
  const response = await apiFetch("/api/bolus/plan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const data = await toJson(response);
  if (!response.ok) {
    throw new Error(data.detail || "Error al planificar bolo");
  }
  return data;
}

export async function calculateBolusWithOptionalSplit(calcPayload, splitSettings) {
  const calcData = await calculateBolus(calcPayload);
  const totalU = calcData.total_u_final ?? calcData.total_u ?? 0;

  if (splitSettings && splitSettings.enabled && totalU > 0) {
    try {
      const planPayload = {
        mode: "dual",
        total_recommended_u: totalU,
        round_step_u: splitSettings.round_step_u || 0.5,
        dual: {
          percent_now: splitSettings.percent_now || 70,
          duration_min: splitSettings.duration_min || 150,
          later_after_min: splitSettings.later_after_min || 150
        }
      };

      const planData = await createBolusPlan(planPayload);

      return {
        kind: "dual",
        calc: calcData,
        plan: planData,
        upfront_u: planData.now_u,
        later_u: planData.later_u_planned,
        duration_min: planData.extended_duration_min ?? planData.later_after_min
      };

    } catch (err) {
      console.warn("Split plan failed, falling back to normal bolus", err);
      return {
        kind: "normal",
        calc: calcData,
        upfront_u: totalU,
        later_u: 0,
        duration_min: 0,
        error: "Split plan failed: " + err.message
      };
    }
  }

  return {
    kind: "normal",
    calc: calcData,
    upfront_u: totalU,
    later_u: 0,
    duration_min: 0
  };
}

export async function recalcSecondBolus(payload) {
  const response = await apiFetch("/api/bolus/recalc-second", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const data = await toJson(response);
  if (!response.ok) {
    throw new Error(data.detail || "Error al recalcular segunda parte");
  }
  return data;
}

export function logout() {
  clearSession();
  try {
    sessionStorage.removeItem(NS_SESSION_KEY);
  } catch (e) {
    console.warn("NS session cleanup failed", e);
  }
  notifyAuthLogout("logout");
}

export async function createBasalEntry(payload) {
  const response = await apiFetch("/api/basal/entry", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al guardar basal");
  return data;
}

export async function getBasalEntries(days = 30) {
  const response = await apiFetch(`/api/basal/history?days=${days}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener historial basal");
  return data;
}

export async function createBasalCheckin(payload) {
  const response = await apiFetch("/api/basal/checkin", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al realizar check-in");
  return data;
}

export async function getBasalCheckins(days = 14) {
  const response = await apiFetch(`/api/basal/checkins?days=${days}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener check-ins");
  return data;
}

export async function getBasalActive() {
  const response = await apiFetch("/api/basal/active");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener basal activa");
  return data;
}

export async function getLatestBasal() {
  const response = await apiFetch("/api/basal/latest");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener última basal");
  return data;
}

export async function runNightScan(nightscoutConfig, targetDate) {
  const payload: any = {
    nightscout_url: nightscoutConfig.url,
    nightscout_token: nightscoutConfig.token
  };
  if (targetDate) {
    payload.target_date = targetDate;
  }

  const response = await apiFetch("/api/basal/night-scan", {
    method: "POST",
    body: JSON.stringify(payload)
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al analizar noche");
  return data;
}

export async function getBasalAdvice(days = 3) {
  const response = await apiFetch(`/api/basal/advice?days=${days}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener consejo basal");
  return data;
}

export async function runAnalysis(days) {
  const response = await apiFetch("/api/analysis/bolus/run", {
    method: "POST",
    body: JSON.stringify({ days }),
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al ejecutar análisis");
  return data;
}

export async function getAnalysisSummary(days) {
  const response = await apiFetch(`/api/analysis/bolus/summary?days=${days}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener resumen");
  return data;
}

export async function generateSuggestions(days = 30) {
  const response = await apiFetch("/api/suggestions/generate", {
    method: "POST",
    body: JSON.stringify({ days }),
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al generar sugerencias");
  return data;
}

export async function getSuggestions(status = "pending") {
  const response = await apiFetch(`/api/suggestions?status=${status}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener sugerencias");
  return data;
}

export async function acceptSuggestion(id, note, proposed_change) {
  const response = await apiFetch(`/api/suggestions/${id}/accept`, {
    method: "POST",
    body: JSON.stringify({ note, proposed_change }),
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al aceptar sugerencia");
  return data;
}

export async function rejectSuggestion(id, note) {
  const response = await apiFetch(`/api/suggestions/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al rechazar sugerencia");
  return data;
}

export async function evaluateSuggestion(id, days = 7) {
  const response = await apiFetch(`/api/suggestions/${id}/evaluate?days=${days}`, {
    method: "POST"
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al evaluar");
  return data;
}

export async function getEvaluations() {
  const response = await apiFetch("/api/suggestions/evaluations");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener evaluaciones");
  return data;
}

export async function getBasalTimeline(days = 14) {
  const response = await apiFetch(`/api/basal/timeline?days=${days}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener timeline basal");
  return data;
}

export async function evaluateBasalChange(days = 7) {
  const response = await apiFetch("/api/basal/evaluate-change", {
    method: "POST",
    body: JSON.stringify({ days })
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al evaluar cambio basal");
  return data;
}

export async function deleteHistoryEntry(dateStr) {
  const response = await apiFetch(`/api/basal/history/${dateStr}`, {
    method: "DELETE"
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al eliminar entrada");
  return data;
}

export async function getNotificationsSummary() {
  const response = await apiFetch("/api/notifications/summary");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener notificaciones");
  return data;
}

export async function markNotificationsSeen(types) {
  const response = await apiFetch("/api/notifications/mark-seen", {
    method: "POST",
    body: JSON.stringify({ types })
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al marcar como vistas");
  return data;
}

export async function getSettings() {
  const response = await apiFetch("/api/settings/");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error obteniendo configuración");
  return data;
}

export async function getMlStatus() {
  const response = await apiFetch("/api/settings/ml-status");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error obteniendo estado ML");
  return data;
}


export async function putSettings(settings, version) {
  const response = await apiFetch("/api/settings/", {
    method: "PUT",
    body: JSON.stringify({ settings, version })
  });
  const data = await toJson(response);

  if (response.status === 409) {
    const err: any = new Error("Conflict");
    err.isConflict = true;
    err.serverVersion = data.server_version;
    err.serverSettings = data.server_settings;
    throw err;
  }

  if (!response.ok) throw new Error(data.detail || "Error guardando configuración");
  return data;
}

export async function testDexcom(config) {
  const response = await apiFetch("/api/dexcom/test", {
    method: "POST",
    body: JSON.stringify(config)
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error probando Dexcom");
  return data;
}

export async function importSettings(settings) {
  const response = await apiFetch("/api/settings/import", {
    method: "POST",
    body: JSON.stringify({ settings })
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error importando configuración");
  return data;
}

export async function exportUserData() {
  const response = await apiFetch("/api/data/export");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al exportar datos");
  return data;
}

export async function fetchBotProactiveStatus() {
  const response = await apiFetch("/api/bot/proactive/status");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error obteniendo estado del bot");
  return data;
}


export async function importUserData(jsonData) {
  const response = await apiFetch("/api/data/import", {
    method: "POST",
    body: JSON.stringify(jsonData)
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al importar datos");
  return data;
}

export async function runAutoScan() {
  const response = await apiFetch("/api/basal/trigger-autoscan", {
    method: "POST"
  });
  const data = await toJson(response);
  if (!response.ok) console.warn("Auto-scan trigger failed", data);
  return data;
}

export async function updateTreatment(id, payload) {
  const response = await apiFetch(`/api/nightscout/treatments/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al actualizar tratamiento");
  return data;
}

export async function deleteTreatment(id) {
  const response = await apiFetch(`/api/nightscout/treatments/${id}`, {
    method: "DELETE"
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al eliminar tratamiento");
  return data;
}

export * from "./bleScale";

// --- FAVORITES ---
export async function getFavorites() {
  const response = await apiFetch("/api/user/favorites");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error obteniendo favoritos");
  return data;
}

export async function saveFavorite(favorite) {
  // Supports full object: name, carbs, fat, protein, notes
  const response = await apiFetch("/api/user/favorites", {
    method: "POST",
    body: JSON.stringify(favorite)
  });
  const data = await toJson(response);
  if (!response.ok) {
    let msg = data.detail || "Error guardando favorito";
    if (typeof msg !== 'string') msg = JSON.stringify(msg);
    throw new Error(msg);
  }
  return data;
}

export async function updateFavorite(id, favorite) {
  const response = await apiFetch(`/api/user/favorites/${id}`, {
    method: "PUT",
    body: JSON.stringify(favorite)
  });
  const data = await toJson(response);
  if (!response.ok) {
    let msg = data.detail || "Error al actualizar favorito";
    if (typeof msg !== 'string') msg = JSON.stringify(msg);
    throw new Error(msg);
  }
  return data;
}

export async function deleteFavorite(id) {
  const response = await apiFetch(`/api/user/favorites/${id}`, {
    method: "DELETE"
  });
  if (!response.ok) {
    const data = await toJson(response);
    throw new Error(data.detail || "Error eliminando favorito");
  }
  return true;
}

// Legacy Alias for backward compatibility
export async function addFavorite(name, carbs) {
  if (typeof name === 'object' && name !== null) {
    return saveFavorite(name);
  }
  return saveFavorite({ name, carbs });
}

export async function getSupplies() {
  const response = await apiFetch("/api/user/supplies");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error obteniendo suministros");
  return data;
}

export async function updateSupply(key, quantity) {
  const response = await apiFetch("/api/user/supplies", {
    method: "POST",
    body: JSON.stringify({ key, quantity })
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error actualizando suministro");
  return data;
}

export async function fetchIsfAnalysis(days = 14) {
  const response = await apiFetch(`/api/isf/analysis?days=${days}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al analizar ISF");
  return data;
}

export async function fetchAutosens() {
  const response = await apiFetch("/api/autosens/calculate");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al calcular Autosens");
  return data;
}


export async function simulateForecast(payload) {
  const response = await apiFetch("/api/forecast/simulate", {
    method: "POST",
    body: JSON.stringify(payload)
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al simular pronóstico");
  return data;
}

export async function toggleSickMode(enabled: boolean) {
  const response = await apiFetch(`/api/events/sick-mode?enabled=${enabled}`, {
    method: "POST"
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al cambiar modo enfermedad");
  return data;
}

export async function getLearningLogs(limit = 20) {
  const response = await apiFetch(`/api/analysis/shadow/logs?limit=${limit}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener logs");
  return data;
}

export async function getLearningSummary() {
  const response = await apiFetch("/api/learning/summary");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener resumen de aprendizaje");
  return data;
}

export async function getLearningClusters() {
  const response = await apiFetch("/api/learning/clusters");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener clusters");
  return data;
}

export async function getLearningClusterDetail(clusterKey: string) {
  const response = await apiFetch(`/api/learning/clusters/${encodeURIComponent(clusterKey)}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener detalle del cluster");
  return data;
}

export async function getLearningEvents(filters: { event_kind?: string; window_status?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.event_kind) params.set("event_kind", filters.event_kind);
  if (filters.window_status) params.set("window_status", filters.window_status);
  const query = params.toString();
  const response = await apiFetch(`/api/learning/events${query ? `?${query}` : ""}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener eventos de aprendizaje");
  return data;
}

export async function updateSettings(settings, version) {
  const resolvedVersion = version ?? settings?.version;
  if (resolvedVersion === undefined || resolvedVersion === null) {
    throw new Error("Falta la versión de configuración para guardar cambios.");
  }
  const cleanSettings = { ...settings };
  if ("version" in cleanSettings) delete cleanSettings.version;
  return putSettings(cleanSettings, resolvedVersion);
}



export async function fetchIngestLogs() {
  const response = await apiFetch("/api/integrations/nutrition/logs");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error fetching logs");
  return data;
}

export async function saveInjectionSite(insulinType, siteId) {
  const response = await apiFetch(`/api/injection/manual`, {
    method: "POST",
    body: JSON.stringify({ insulin_type: insulinType, point_id: siteId })
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error saving site");
  return data;
}

export function getSiteLabel(type, id) {
  if (!id) return "";
  // Basic formatting: "abdomen_right" -> "Abdomen Right"
  return id.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

export async function saveActivePlan(plan) {
  const response = await apiFetch("/api/bolus/active-plans", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(plan)
  });
  return toJson(response);
}
