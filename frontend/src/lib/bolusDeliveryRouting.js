function finiteNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/**
 * Convert the authoritative backend calculation into the delivery shape used
 * by the UI. In particular, never collapse a backend dual/extended result into
 * a single immediate dose.
 */
export function resolveBackendBolusDelivery(calcData) {
  const totalU = finiteNumber(calcData?.total_u_final ?? calcData?.total_u, 0);
  const laterU = Math.max(0, finiteNumber(calcData?.later_u, 0));
  const backendKind = calcData?.kind;
  const isExtended = (backendKind === 'dual' || backendKind === 'extended') && laterU > 0;

  if (isExtended) {
    const suppliedUpfront = Number(calcData?.upfront_u);
    const upfrontU = Number.isFinite(suppliedUpfront)
      ? Math.max(0, suppliedUpfront)
      : Math.max(0, totalU - laterU);

    return {
      kind: backendKind,
      calc: calcData,
      upfront_u: upfrontU,
      later_u: laterU,
      duration_min: Math.max(0, finiteNumber(calcData?.duration_min, 0)),
    };
  }

  return {
    kind: 'normal',
    calc: calcData,
    upfront_u: totalU,
    later_u: 0,
    duration_min: 0,
  };
}
