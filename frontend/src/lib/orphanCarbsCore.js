export function parseCoveredCarbs(notes) {
  if (!notes) return null;

  const explicit = notes.match(/\[covered_carbs=([0-9]+(?:[.,][0-9]+)?)\]/i);
  if (explicit) {
    const parsed = Number(explicit[1].replace(',', '.'));
    return Number.isFinite(parsed) ? parsed : null;
  }

  const legacy = notes.match(/\bGr:\s*([0-9]+(?:[.,][0-9]+)?)/i);
  if (legacy) {
    const parsed = Number(legacy[1].replace(',', '.'));
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
}

export function isLinkedToIngestion(treatment, ingestionId) {
  if (!treatment?.notes || !ingestionId) return false;
  return treatment.notes.includes(`[linked_ingestion_id=${ingestionId}]`);
}

export function calculateCoveredCarbsForIngestion(treatments, ingestionId) {
  return treatments
    .filter((t) => isLinkedToIngestion(t, ingestionId))
    .map((t) => {
      const parsed = parseCoveredCarbs(t.notes);
      if (parsed !== null) return parsed;
      const stored = Number(t.carbs || 0);
      return Number.isFinite(stored) && stored > 0 ? stored : 0;
    })
    .filter((value) => value > 0)
    .reduce((sum, value) => sum + value, 0);
}

export function calculateNewCarbsToCover(totalCarbs, alreadyCoveredCarbs) {
  const total = Number(totalCarbs);
  const covered = Number(alreadyCoveredCarbs);
  if (!Number.isFinite(total) || total < 0) {
    throw new Error('Los hidratos totales de la ingesta no son válidos.');
  }
  if (!Number.isFinite(covered) || covered < 0) {
    throw new Error('Los hidratos ya cubiertos no son válidos.');
  }
  return Math.max(0, total - covered);
}
