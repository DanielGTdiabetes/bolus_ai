function normalizeBaseUrl(value?: string | null) {
  return value ? String(value).replace(/\/$/, "") : null;
}

function guessRenderBackendBase(locationLike?: Location) {
  if (!locationLike) return null;
  const host = locationLike.hostname || "";

  // Render has the frontend and backend on separate hosts.
  // If we are on the public frontend host, force the backend host to avoid hitting the static server.
  if (host === "bolus-ai.onrender.com") {
    return "https://bolus-ai-1.onrender.com";
  }

  // Generic Render fallback: if we are on any other Render frontend but not the backend host, prefer the backend.
  if (host.endsWith(".onrender.com") && !host.includes("bolus-ai-1")) {
    return "https://bolus-ai-1.onrender.com";
  }

  return null;
}

export function getApiBase() {
  const envBase =
    normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL) ||
    normalizeBaseUrl(import.meta.env.VITE_API_URL);
  if (envBase) return envBase;

  const win = typeof window !== "undefined" ? window : undefined;
  const renderBase = guessRenderBackendBase(win?.location);
  if (renderBase) return renderBase;

  return normalizeBaseUrl(win?.location?.origin) || "";
}

const API_BASE = getApiBase();
const TOKEN_KEY = "bolusai_token";
const USER_KEY = "bolusai_user";
const NS_STORAGE_KEY = "bolusai_ns_config"; // Legacy (localStorage)
const NS_SESSION_KEY = "bolusai_ns_config_session";

let unauthorizedHandler = null;

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

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
  return localStorage.getItem(TOKEN_KEY);
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

export async function apiFetch(path: string, options: ApiOptions = {}) {
  const headers: Record<string, string> = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body && !headers["Content-Type"]) {
    // Only set JSON if not FormData (FormData usually handled by browser or specific heuristic)
    // But here we rely on caller to NOT set content-type for FormData.
    // If body is string, it's JSON.
    if (typeof options.body === 'string') {
      headers["Content-Type"] = "application/json";
    }
  }

  const token = getStoredToken();
  const hadToken = Boolean(token); // Track if we had a token at request time
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response;
  try {
    const fetchUrl = new URL(path, API_BASE || window.location.origin);
    response = await fetch(fetchUrl, {
      ...options,
      headers,
    });
  } catch (error) {
    console.error("Fetch Error:", error);
    if (error instanceof TypeError && (error.message.includes("fetch") || error.message.includes("network") || error.message.includes("Network"))) {
      throw new Error("No se pudo conectar con el servidor (Offline o bloqueado). Verifique su conexión.");
    }
    throw new Error("Error de conexión: " + error.message);
  }

  if (response.status === 401) {
    // Only clear session and trigger handler if this request had a token attached.
    // This prevents race conditions where old requests without tokens (made before login)
    // clear the newly saved session token.
    if (hadToken) {
      clearSession();
      if (unauthorizedHandler) unauthorizedHandler();
    }
    // Always throw consistent error message to avoid breaking UI handlers
    throw new Error("Sesión caducada. Vuelve a iniciar sesión.");
  }

  if (response.status === 0) {
    throw new Error("Error de red desconocido (Posible CORS o servidor caído).");
  }

  return response;
}

export async function loginRequest(username, password) {
  const response = await apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  const data = await toJson(response);
  if (!response.ok) {
    throw new Error(data.detail || "Credenciales inválidas");
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

export async function saveNightscoutConfig(config) {
  // Legacy support or usage of new endpoint if config matches new structure
  // But strictly this function was PUT /api/nightscout/config (Legacy)
  const response = await apiFetch("/api/nightscout/config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al guardar configuración");
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

  const response = await fetch(new URL("/api/vision/estimate", API_BASE || window.location.origin), {
    method: "POST",
    headers,
    body: formData,
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
  if (unauthorizedHandler) unauthorizedHandler();
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

export async function updateSettings(settings) {
  // Wrapper for putSettings to simplify usage
  return putSettings(settings, settings.version);
}

export async function getNutritionDraft() {
  const response = await apiFetch("/api/integrations/nutrition/draft");
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error obteniendo draft");
  return data;
}

export async function closeNutritionDraft() {
  const response = await apiFetch("/api/integrations/nutrition/draft/close", { method: "POST" });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error cerrando draft");
  return data;
}

export async function discardNutritionDraft() {
  const response = await apiFetch("/api/integrations/nutrition/draft/discard", { method: "POST" });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error descartando draft");
  return data;
}
