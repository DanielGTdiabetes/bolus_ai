import { apiFetch } from './api';

function parseJsonResponse(response) {
  return response
    .json()
    .catch(() => ({}))
    .then((data) => ({ ok: response.ok, data, status: response.status }));
}

export async function analyzeMenuImage(imageFile) {
  const formData = new FormData();
  formData.append('image', imageFile);

  const response = await apiFetch('/api/restaurant/analyze_menu', {
    method: 'POST',
    body: formData,
  });

  const { ok, data } = await parseJsonResponse(response);
  if (!ok) {
    throw new Error(data.detail || 'No se pudo analizar la carta');
  }
  return data;
}

export async function comparePlateImage({ imageFile, expectedCarbs }) {
  const formData = new FormData();
  if (imageFile) {
    formData.append('image', imageFile);
  }
  formData.append('expectedCarbs', expectedCarbs);

  const response = await apiFetch('/api/restaurant/compare_plate', {
    method: 'POST',
    body: formData,
  });

  const { ok, data } = await parseJsonResponse(response);
  if (!ok) {
    throw new Error(data.detail || 'No se pudo comparar el plato');
  }
  return data;
}

export async function analyzePlateImage(imageFile) {
  const formData = new FormData();
  formData.append('image', imageFile);

  const response = await apiFetch('/api/restaurant/analyze_plate', {
    method: 'POST',
    body: formData,
  });

  const { ok, data } = await parseJsonResponse(response);
  if (!ok) {
    throw new Error(data.detail || 'No se pudo analizar el plato');
  }
  return data;
}

export async function calculateRestaurantAdjustment({ expectedCarbs, actualCarbs, confidence }) {
  const formData = new FormData();
  formData.append('expectedCarbs', expectedCarbs);
  formData.append('actualCarbs', actualCarbs);
  if (confidence !== undefined && confidence !== null) {
    formData.append('confidence', confidence);
  }

  const response = await apiFetch('/api/restaurant/compare_plate', {
    method: 'POST',
    body: formData,
  });

  const { ok, data } = await parseJsonResponse(response);
  if (!ok) {
    throw new Error(data.detail || 'No se pudo calcular el ajuste');
  }
  return data;
}
