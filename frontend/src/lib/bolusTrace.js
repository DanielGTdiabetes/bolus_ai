function finiteOrNull(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Build a retrospective trace from an already-computed backend response.
 * This object is persisted for audit/learning only and is never a dosing input.
 */
export function buildClientBolusTrace(result, acceptedU, source = 'app') {
  const calc = result?.calc || result || {};
  const glucose = calc?.glucose || null;
  const used = calc?.used_params || calc?.usedParams || {};

  const recommendedU = finiteOrNull(calc?.total_u_final ?? calc?.total_u);
  const accepted = finiteOrNull(acceptedU);

  return {
    snapshot: {
      schema_version: 1,
      source,
      recommended_u: recommendedU,
      accepted_u: accepted,
      kind: result?.kind || calc?.kind || 'normal',
      meal_component_u: finiteOrNull(calc?.meal_bolus_u),
      correction_component_u: finiteOrNull(calc?.correction_u),
      iob_u: finiteOrNull(calc?.iob_u),
      iob_applied_to_correction_u: finiteOrNull(calc?.iob_applied_to_correction_u),
      total_u_raw: finiteOrNull(calc?.total_u_raw),
      total_u_final: recommendedU,
      upfront_u: finiteOrNull(result?.upfront_u ?? calc?.upfront_u),
      later_u: finiteOrNull(result?.later_u ?? calc?.later_u),
      duration_min: finiteOrNull(result?.duration_min ?? calc?.duration_min),
      glucose,
      warnings: Array.isArray(calc?.warnings) ? [...calc.warnings] : [],
      assumptions: Array.isArray(calc?.assumptions) ? [...calc.assumptions] : [],
      explain: Array.isArray(calc?.explain) ? [...calc.explain] : [],
    },
    applied_ratios: { ...used },
    context: {
      bg: finiteOrNull(glucose?.mgdl),
      trend: glucose?.trend ?? null,
      iob: finiteOrNull(calc?.iob_u),
      glucose_source: glucose?.source ?? null,
      glucose_age_minutes: finiteOrNull(glucose?.age_minutes),
      glucose_is_stale: Boolean(glucose?.is_stale),
    },
  };
}
