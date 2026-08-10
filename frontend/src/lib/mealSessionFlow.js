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

export const MEAL_SESSION_MAX_AGE_HOURS = 8;

function nonNegative(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, parsed);
}

function parseBackendUtcTimestamp(value) {
  if (!value || typeof value !== 'string') return null;
  // The current backend stores UTC as a naive SQL timestamp. Treat an ISO
  // value without timezone information as UTC instead of browser-local time.
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const parsed = Date.parse(hasZone ? value : `${value}Z`);
  return Number.isFinite(parsed) ? parsed : null;
}

export function isMealSessionStale(
  session,
  nowMs = Date.now(),
  maxAgeHours = MEAL_SESSION_MAX_AGE_HOURS,
) {
  if (!session?.started_at) return true;
  const startedMs = parseBackendUtcTimestamp(session.started_at);
  if (startedMs == null) return true;
  const ageMs = Number(nowMs) - startedMs;
  if (!Number.isFinite(ageMs)) return true;
  // A significantly future timestamp is also unsafe to auto-resume.
  if (ageMs < -10 * 60_000) return true;
  return ageMs > Math.max(1, Number(maxAgeHours) || MEAL_SESSION_MAX_AGE_HOURS) * 60 * 60_000;
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
