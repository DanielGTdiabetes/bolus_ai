const CONFIG_FIELDS_THAT_MUST_STAY_SERVER_SIDE = [
  'cr_g_per_u',
  'isf_mgdl_per_u',
  'target_mgdl',
  'dia_hours',
  'insulin_model',
  'insulin_peak_minutes',
  'round_step_u',
  'max_bolus_u',
  'max_correction_u',
  'max_iob_u',
  'min_bolus_interval_min',
  'techne',
  'warsaw_safety_factor',
  'warsaw_safety_factor_dual',
  'warsaw_trigger_threshold_kcal',
  'use_fiber_deduction',
  'fiber_factor',
  'fiber_threshold',
];

/**
 * Build the request-specific part of an ONLINE bolus calculation.
 *
 * Persistent dosing configuration (ICR, ISF, target, DIA, insulin model,
 * safety ceilings, Warsaw, Techne, etc.) belongs to the backend user settings
 * and must not be copied into each browser request. This keeps the web/mobile
 * UI and Telegram on the same authoritative configuration.
 *
 * The offline emergency calculator is a separate path and is intentionally not
 * affected by this helper.
 */
export function buildOnlineBolusPayload({
  carbsG,
  fatG = 0,
  proteinG = 0,
  fiberG = 0,
  bgMgdl = null,
  mealSlot,
  carbProfile = null,
  alcohol = false,
  exercise = { planned: false, minutes: 0, intensity: 'moderate' },
  autosensOverride,
}) {
  const payload = {
    carbs_g: Number(carbsG) || 0,
    fat_g: Number(fatG) || 0,
    protein_g: Number(proteinG) || 0,
    fiber_g: Number(fiberG) || 0,
    bg_mgdl: bgMgdl == null || Number.isNaN(Number(bgMgdl)) ? null : Number(bgMgdl),
    meal_slot: mealSlot,
    carb_profile: carbProfile ?? null,
    alcohol: Boolean(alcohol),
    exercise: exercise || { planned: false, minutes: 0, intensity: 'moderate' },
  };

  // Per-request Autosens override is allowed only when explicitly requested.
  // Otherwise omission means "use the backend user's saved setting".
  if (typeof autosensOverride === 'boolean') {
    payload.enable_autosens = autosensOverride;
  }

  return payload;
}

export function containsClientDosingConfig(payload) {
  return CONFIG_FIELDS_THAT_MUST_STAY_SERVER_SIDE.some((field) =>
    Object.prototype.hasOwnProperty.call(payload || {}, field)
  );
}
