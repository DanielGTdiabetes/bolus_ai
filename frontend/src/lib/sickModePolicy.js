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
export function resolveSickModeDosingPolicy({ icr, isf, isSick = false }) {
  const resolvedIcr = finitePositive(icr, 'ICR');
  const resolvedIsf = finitePositive(isf, 'ISF');

  return {
    icr: resolvedIcr,
    isf: resolvedIsf,
    active: Boolean(isSick),
    automaticDoseAdjustment: false,
    warning: isSick
      ? 'Modo Enfermedad activo: ajuste automático de dosis desactivado; se usan los ratios configurados.'
      : null,
  };
}
