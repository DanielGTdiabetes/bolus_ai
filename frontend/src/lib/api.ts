const API_BASE = (import.meta.env.VITE_API_BASE_URL || window.location.origin).replace(/\/$/, "");
const TOKEN_KEY = "bolusai_token";
const USER_KEY = "bolusai_user";

let unauthorizedHandler = null;

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

export function getApiBase() {
  return API_BASE;
}

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

export async function apiFetch(path: string, options: any = {}) {
  const headers: any = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const token = getStoredToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(new URL(path, API_BASE || window.location.origin), {
    ...options,
    headers,
  });

  if (response.status === 401) {
    clearSession();
    if (unauthorizedHandler) unauthorizedHandler();
    throw new Error("Sesión caducada. Vuelve a iniciar sesión.");
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
  const response = await apiFetch("/api/health");
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



async function apiGet(path: string, token?: string) {
  const options: RequestInit = {};
  if (token) {
    options.headers = { Authorization: `Bearer ${token}` };
  }
  const response = await apiFetch(path, options);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error en petición GET");
  return data;
}

export async function getCurrentGlucose(config) {
  if (!config || !config.url) {
    return { ok: false, error: "No configurado (local)" };
  }
  const response = await apiFetch("/api/nightscout/current", {
    method: "POST",
    body: JSON.stringify(config)
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener glucosa");
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
  const response = await apiFetch("/api/nightscout/config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al guardar configuración");
  return data;
}

export async function estimateCarbsFromImage(file: any, options: any = {}) {
  const formData = new FormData();
  formData.append("image", file);
  if (options.meal_slot) formData.append("meal_slot", options.meal_slot);
  if (options.bg_mgdl) formData.append("bg_mgdl", options.bg_mgdl);
  if (options.target_mgdl) formData.append("target_mgdl", options.target_mgdl);
  if (options.portion_hint) formData.append("portion_hint", options.portion_hint);
  if (typeof options.prefer_extended !== 'undefined') formData.append("prefer_extended", options.prefer_extended);

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

  // Special handle for apiFetch with FormData: do NOT set Content-Type
  const headers: any = { Accept: "application/json" };
  const token = getStoredToken();
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
  let url = "/api/bolus/iob";
  if (config) {
    const params = new URLSearchParams();
    if (config.url) params.append("nightscout_url", config.url);
    if (config.token) params.append("nightscout_token", config.token);
    url += "?" + params.toString();
  }
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
  let url = "/api/nightscout/treatments";
  if (config) {
    const params = new URLSearchParams();
    if (config.url) params.append("url", config.url);
    if (config.token) params.append("token", config.token);
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
  // 1. Calculate Standard Bolus
  const calcData = await calculateBolus(calcPayload);

  // Decide total to use (final clamped or fallback)
  const totalU = calcData.total_u_final ?? calcData.total_u ?? 0;

  // 2. Check if Split needed
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
      // Fallback to normal
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

  // 3. Normal Bolus
  return {
    kind: "normal",
    calc: calcData,
    upfront_u: totalU,
    later_u: 0,
    duration_min: 0
  };
}


/**
 * Recalculates the second part (U2) of a dual bolus.
 * @param {{
 *   later_u_planned: number,
 *   carbs_additional_g?: number,
 *   params: {
 *     cr_g_per_u: number,
 *     isf_mgdl_per_u: number,
 *     target_bg_mgdl: number,
 *     round_step_u: number,
 *     max_bolus_u: number,
 *     stale_bg_minutes: number
 *   },
 *   nightscout?: {
 *     url: string,
 *     token: string,
 *     units: string
 *   }
 * }} payload
 * @returns {Promise<{
 *   bg_now_mgdl?: number,
 *   bg_age_min?: number,
 *   iob_now_u?: number,
 *   u2_recommended_u: number,
 *   cap_u?: number,
 *   warnings: string[],
 *   components: any
 * }>}
 */
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

// --- Basal API ---

export async function createBasalEntry(payload: any) {
  const response = await apiFetch("/api/basal/entry", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al guardar basal");
  return data;
}

export async function getBasalEntries(days = 30) {
  const response = await apiFetch(`/api/basal/entries?days=${days}`);
  const data = await toJson(response);
  if (!response.ok) throw new Error(data.detail || "Error al obtener historial basal");
  return data;
}

export async function createBasalCheckin(nightscoutConfig: any) {
  const payload = {
    nightscout_url: nightscoutConfig.url,
    nightscout_token: nightscoutConfig.token
  };
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
