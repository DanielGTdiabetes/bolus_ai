import { apiFetch } from './api';

function parseJsonResponse(response) {
  return response
    .json()
    .catch(() => ({}))
    .then((data) => ({ ok: response.ok, data, status: response.status }));
}

export async function analyzeMenuImage(imageFile, options = {}) {
  const formData = new FormData();
  formData.append('image', imageFile);

  const response = await apiFetch('/api/restaurant/analyze_menu', {
    method: 'POST',
    body: formData,
    signal: options.signal,
  });

  const { ok, data } = await parseJsonResponse(response);
  if (!ok) {
    throw new Error(data.detail || 'No se pudo analizar la carta');
  }
  return data;
}

export async function analyzeMenuText(textDescription, options = {}) {
  const formData = new FormData();
  formData.append('description', textDescription);

  const response = await apiFetch('/api/restaurant/analyze_menu_text', {
    method: 'POST',
    body: formData,
    signal: options.signal,
  });

  const { ok, data } = await parseJsonResponse(response);
  if (!ok) {
    throw new Error(data.detail || 'No se pudo analizar el texto del menú');
  }
  return data;
}

export async function comparePlateImage({ imageFile, expectedCarbs, signal }) {
  const formData = new FormData();
  if (imageFile) {
    formData.append('image', imageFile);
  }
  formData.append('expectedCarbs', expectedCarbs);

  const response = await apiFetch('/api/restaurant/compare_plate', {
    method: 'POST',
    body: formData,
    signal,
  });

  const { ok, data } = await parseJsonResponse(response);
  if (!ok) {
    throw new Error(data.detail || 'No se pudo comparar el plato');
  }
  return data;
}

export async function analyzePlateImage(imageFile, options = {}) {
  const formData = new FormData();
  formData.append('image', imageFile);

  const response = await apiFetch('/api/restaurant/analyze_plate', {
    method: 'POST',
    body: formData,
    signal: options.signal,
  });

  const { ok, data } = await parseJsonResponse(response);
  if (!ok) {
    throw new Error(data.detail || 'No se pudo analizar el plato');
  }
  return data;
}

export async function calculateRestaurantAdjustment({ expectedCarbs, actualCarbs, confidence, signal }) {
  const formData = new FormData();
  formData.append('expectedCarbs', expectedCarbs);
  formData.append('actualCarbs', actualCarbs);
  if (confidence !== undefined && confidence !== null) {
    formData.append('confidence', confidence);
  }

  const response = await apiFetch('/api/restaurant/compare_plate', {
    method: 'POST',
    body: formData,
    signal,
  });

  const { ok, data } = await parseJsonResponse(response);
  if (!ok) {
    throw new Error(data.detail || 'No se pudo calcular el ajuste');
  }
  return data;
}

// --- Persistence ---

export async function startRestaurantSession(payload) {
  const response = await apiFetch('/api/restaurant/session/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const { ok, data } = await parseJsonResponse(response);
  if (!ok) throw new Error(data.detail || 'Fallo al iniciar sesión persistente');
  return data;
}

export async function addPlateToSession(sessionId, plateData) {
  const response = await apiFetch(`/api/restaurant/session/${sessionId}/plate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(plateData),
  });
  const { ok, data } = await parseJsonResponse(response);
  if (!ok) throw new Error(data.detail || 'Fallo actualizando sesión');
  return data;
}

export async function finalizeRestaurantSession(sessionId, outcomeData = {}) {
  const response = await apiFetch(`/api/restaurant/session/${sessionId}/finalize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(outcomeData),
  });
  const { ok, data } = await parseJsonResponse(response);
  if (!ok) throw new Error(data.detail || 'Fallo finalizando sesión');
  return data;
}
