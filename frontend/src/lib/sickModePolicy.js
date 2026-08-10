function finitePositive(value, name) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${name} inválido para cálculo`);
  }
  return parsed;
}

/**
 * Sick mode is currently a context flag only.
 *
 * It MUST NOT silently alter ICR/ISF in the frontend. Any future dosing
 * adjustment has to be represented explicitly in the authoritative backend
 * engine, with the same behaviour for app, Telegram and other clients.
 */
export function resolveSickModeDosingPolicy({ icr, isf, isSick = false } = {}) {
  const policy = {
    active: Boolean(isSick),
    automaticDoseAdjustment: false,
    warning: isSick
      ? 'Modo Enfermedad activo: ajuste automático de dosis desactivado; se usan los ratios configurados.'
      : null,
  };

  // Backward-compatible validation for callers/tests that provide ratios.
  // Online dosing no longer needs browser copies of these values.
  if (icr != null) policy.icr = finitePositive(icr, 'ICR');
  if (isf != null) policy.isf = finitePositive(isf, 'ISF');
  return policy;
}
