export function createApiFetch({
  fetchImpl,
  getToken,
  clearToken,
  onLogout,
  resolveUrl,
  isPublicEndpoint,
  isDev = false,
  onMissingToken,
  warn = console.warn
}) {
  let missingTokenNotified = false;

  return async function apiFetch(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body && !headers["Content-Type"]) {
      if (typeof options.body === "string") {
        headers["Content-Type"] = "application/json";
      }
    }

    const token = getToken();
    const hadToken = Boolean(token);
    if (token) {
      headers.Authorization = `Bearer ${token}`;
      missingTokenNotified = false;
    } else if (!isPublicEndpoint(path)) {
      if (isDev) warn(`[apiFetch] Missing auth token for ${path}`);
      if (!missingTokenNotified) {
        missingTokenNotified = true;
        if (onMissingToken) onMissingToken();
      }
    }

    let response;
    try {
      response = await fetchImpl(resolveUrl(path), {
        ...options,
        headers
      });
    } catch (error) {
      console.error("Fetch Error:", error);
      if (error instanceof TypeError && (error.message.includes("fetch") || error.message.includes("network") || error.message.includes("Network"))) {
        throw new Error("No se pudo conectar con el servidor (Offline o bloqueado). Verifique su conexión.");
      }
      throw new Error("Error de conexión: " + error.message);
    }

    if (response.status === 401) {
      if (hadToken) {
        if (clearToken) clearToken();
        if (onLogout) onLogout("unauthorized");
      }
      throw new Error("Sesión caducada. Vuelve a iniciar sesión.");
    }

    if (response.status === 0) {
      throw new Error("Error de red desconocido (Posible CORS o servidor caído).");
    }

    return response;
  };
}
