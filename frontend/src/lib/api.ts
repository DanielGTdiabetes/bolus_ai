export function getApiBase() {
  return (import.meta.env.VITE_API_BASE_URL || window.location.origin).replace(/\/$/, "");
}

// ... (existing code top block)

// Append to file at the end to keep it simple, or insert if I can.
// I'll rewrite the whole file since it's cleaner.

const API_BASE = (import.meta.env.VITE_API_BASE_URL || window.location.origin).replace(/\/$/, "");
const TOKEN_KEY = "bolusai_token";
const USER_KEY = "bolusai_user";
const NS_STORAGE_KEY = "bolusai_ns_config"; // Added

let unauthorizedHandler = null;

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

// Helper: NS Config Local
export function getLocalNsConfig() {
  try {
    return JSON.parse(localStorage.getItem(NS_STORAGE_KEY));
  } catch (e) {
    return null;
  }
}

export function saveLocalNsConfig(config) {
  localStorage.setItem(NS_STORAGE_KEY, JSON.stringify(config));
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

async function toJson(response) {
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
    clearSession();
    if (unauthorizedHandler) unauthorizedHandler();
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
    const detail = data.detail || data.message || "No se pudo calcular";
    throw new Error(detail);
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
}

export async function estimateCarbsFromImage(file: File, options: VisionOptions = {}) {
  const formData = new FormData();
  formData.append("image", file);
  if (options.meal_slot) formData.append("meal_slot", options.meal_slot);
  if (options.bg_mgdl) formData.append("bg_mgdl", String(options.bg_mgdl));
  if (options.target_mgdl) formData.append("target_mgdl", String(options.target_mgdl));
  if (options.portion_hint) formData.append("portion_hint", options.portion_hint);

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
          duration_min: splitSettings.duration_min || 120,
          later_after_min: splitSettings.later_after_min || 120
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

export async function runAutoScan() {
  const response = await apiFetch("/api/basal/trigger-autoscan", {
    method: "POST"
  });
  const data = await toJson(response);
  if (!response.ok) console.warn("Auto-scan trigger failed", data);
  return data;
}

export * from "./bleScale";
