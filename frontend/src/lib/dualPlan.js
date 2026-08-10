function finiteNumber(value, fallback = null) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function nonNegative(value, fallback = 0) {
  const parsed = finiteNumber(value, fallback);
  return Math.max(0, parsed ?? fallback);
}

export function getAuthoritativeBolusTotal(result) {
  const calc = result?.calc || result || {};
  const total = finiteNumber(calc?.total_u_final ?? calc?.total_u, null);
  if (total != null) return Math.max(0, total);

  return nonNegative(result?.upfront_u, 0) + nonNegative(result?.later_u, 0);
}

/**
 * Normalize both client-created dual plans and backend-generated Warsaw/extended
 * results into one persistent shape.
 *
 * This function records the original recommendation and the accepted upfront
 * dose. It does not recalculate or alter the planned later dose.
 */
export function buildPersistentDualPlan({
  result,
  treatmentId,
  acceptedUpfrontU,
  createdAtTs = Date.now(),
  mealSlot = null,
  source = 'app',
}) {
  const calc = result?.calc || result || {};
  const plan = result?.plan || {};

  const laterU = nonNegative(
    result?.later_u ?? plan?.later_u_planned ?? calc?.later_u,
    0,
  );
  const durationMin = nonNegative(
    result?.duration_min ?? plan?.extended_duration_min ?? calc?.duration_min,
    0,
  );
  const laterAfterMin = nonNegative(
    plan?.later_after_min ?? durationMin,
    durationMin,
  );
  const acceptedUpfront = nonNegative(acceptedUpfrontU, 0);
  const totalRecommended = nonNegative(
    plan?.total_recommended_u ?? calc?.total_u_final ?? calc?.total_u,
    acceptedUpfront + laterU,
  );

  const stableId = plan?.plan_id || treatmentId;
  if (!stableId) {
    throw new Error('No se puede persistir un plan dual sin identificador estable');
  }

  return {
    id: stableId,
    plan_id: stableId,
    treatment_id: treatmentId || null,
    mode: plan?.mode || 'dual',
    source,
    meal_slot: mealSlot || calc?.used_params?.meal_slot || null,
    total_recommended_u: totalRecommended,
    upfront_u: acceptedUpfront,
    later_u_planned: laterU,
    later_after_min: laterAfterMin,
    extended_duration_min: durationMin || null,
    created_at_ts: createdAtTs,
    status: 'pending',
  };
}
