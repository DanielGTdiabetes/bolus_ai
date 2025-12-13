const API_BASE = (window.__BOLUS_API_BASE__ || window.location.origin).replace(/\/$/, "");
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

export async function apiFetch(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
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

export async function recommendBolus(payload) {
  const response = await apiFetch("/api/bolus/recommend", {
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

export function logout() {
  clearSession();
  if (unauthorizedHandler) unauthorizedHandler();
}

