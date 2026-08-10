import { apiFetch, toJson } from './api';

async function requestJson(path, options = {}) {
  const response = await apiFetch(path, options);
  const data = await toJson(response);
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === 'string'
      ? detail
      : (detail?.message || data?.message || `Error HTTP ${response.status}`);
    throw new Error(message);
  }
  return data;
}

export async function getActiveMealSession() {
  const data = await requestJson('/api/meal-sessions/active');
  return data?.session || null;
}

export async function startMealSession({ mealSlot, label = 'Comida larga', source = 'app' } = {}) {
  const data = await requestJson('/api/meal-sessions/start', {
    method: 'POST',
    body: JSON.stringify({
      meal_slot: mealSlot || null,
      label,
      source,
    }),
  });
  return data?.session || null;
}

export async function addMealSessionCarbs(sessionId, payload) {
  if (!sessionId) throw new Error('Falta meal session id');
  return requestJson(`/api/meal-sessions/${encodeURIComponent(sessionId)}/carbs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function linkTreatmentToMealSession(sessionId, treatmentId) {
  if (!sessionId) throw new Error('Falta meal session id');
  if (!treatmentId) throw new Error('Falta treatment id');
  return requestJson(`/api/meal-sessions/${encodeURIComponent(sessionId)}/link-treatment`, {
    method: 'POST',
    body: JSON.stringify({ treatment_id: treatmentId }),
  });
}

export async function closeMealSession(sessionId) {
  if (!sessionId) throw new Error('Falta meal session id');
  return requestJson(`/api/meal-sessions/${encodeURIComponent(sessionId)}/close`, {
    method: 'POST',
  });
}

export async function cancelMealSession(sessionId) {
  if (!sessionId) throw new Error('Falta meal session id');
  return requestJson(`/api/meal-sessions/${encodeURIComponent(sessionId)}/cancel`, {
    method: 'POST',
  });
}
