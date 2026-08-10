const FORBIDDEN_DOSING_FIELDS = [
  'target_mgdl',
  'cr_g_per_u',
  'isf_mgdl_per_u',
  'dia_hours',
  'insulin_model',
  'round_step_u',
  'max_bolus_u',
  'enable_autosens',
];

function nonNegative(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, parsed);
}

export function createMealSessionEventId() {
  return globalThis.crypto?.randomUUID?.()
    ?? `meal-event-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Builds a ledger event for the plate the user explicitly says is being added
 * to the current long meal. This is meal bookkeeping only: no dosing settings,
 * IOB overrides or Autosens flags are allowed in this payload.
 */
export function buildMealSessionPlatePayload({
  clientEventId,
  carbs,
  mealMeta,
  foodName,
  source = 'app',
}) {
  if (!clientEventId) throw new Error('Falta identificador del plato');

  const payload = {
    client_event_id: String(clientEventId),
    carbs_g: nonNegative(carbs),
    fat_g: nonNegative(mealMeta?.fat),
    protein_g: nonNegative(mealMeta?.protein),
    fiber_g: nonNegative(mealMeta?.fiber),
    label: foodName?.trim() || null,
    source,
  };

  for (const field of FORBIDDEN_DOSING_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(payload, field)) {
      throw new Error(`Campo de dosificación no permitido en meal session: ${field}`);
    }
  }
  return payload;
}

export function summarizeMealSessionProgress(session) {
  return {
    carbsRecordedG: nonNegative(session?.carbs_recorded_g),
    carbsSubmittedForBolusG: nonNegative(session?.carbs_submitted_for_bolus_g),
    acceptedInsulinU: nonNegative(session?.accepted_insulin_u),
    eventCount: Math.max(0, Number(session?.event_count) || 0),
  };
}
