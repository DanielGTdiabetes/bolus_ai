export const MANUAL_BOLUS_LIMITS = Object.freeze({
  glucoseMin: 40,
  glucoseMax: 400,
  targetMin: 60,
  targetMax: 250,
  carbsMax: 500,
  isfMin: 5,
  isfMax: 500,
  icrMin: 1,
  icrMax: 200,
  iobMin: 0,
  iobMax: 30,
  maxBolusMin: 0.05,
  maxBolusMax: 50,
  roundStepMin: 0.01,
  roundStepMax: 1,
  hypoStop: 70,
});

function parseRequiredNumber(value, label) {
  if (value === "" || value === null || value === undefined) {
    throw new Error(`${label} es obligatorio.`);
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${label} debe ser un número finito.`);
  }
  return parsed;
}

function ensureRange(value, min, max, label) {
  if (value < min || value > max) {
    throw new Error(`${label} debe estar entre ${min} y ${max}.`);
  }
  return value;
}

function roundToStep(value, step) {
  return Math.round((value + Number.EPSILON) / step) * step;
}

/**
 * Calculadora de emergencia sin red.
 *
 * Mantiene deliberadamente un subconjunto pequeño y conservador del motor central:
 * - HC = hidratos NUEVOS que se van a cubrir ahora.
 * - El IOB sólo reduce la corrección positiva, nunca el componente de comida.
 * - Una glucosa <70 mg/dL bloquea cualquier recomendación de insulina.
 * - No aplica Autosens, Warsaw, ejercicio, tendencia CGM ni otros modos dinámicos.
 */
export function calculateManualBolus(input) {
  const limits = MANUAL_BOLUS_LIMITS;
  const glucose = ensureRange(
    parseRequiredNumber(input.glucose, "Glucosa"),
    limits.glucoseMin,
    limits.glucoseMax,
    "Glucosa"
  );
  const carbs = ensureRange(
    parseRequiredNumber(input.carbs, "Hidratos nuevos"),
    0,
    limits.carbsMax,
    "Hidratos nuevos"
  );
  const target = ensureRange(
    parseRequiredNumber(input.target, "Objetivo"),
    limits.targetMin,
    limits.targetMax,
    "Objetivo"
  );
  const isf = ensureRange(
    parseRequiredNumber(input.isf, "ISF"),
    limits.isfMin,
    limits.isfMax,
    "ISF"
  );
  const icr = ensureRange(
    parseRequiredNumber(input.icr, "ICR"),
    limits.icrMin,
    limits.icrMax,
    "ICR"
  );
  const iob = ensureRange(
    parseRequiredNumber(input.iob, "IOB"),
    limits.iobMin,
    limits.iobMax,
    "IOB"
  );
  const maxBolus = ensureRange(
    parseRequiredNumber(input.maxBolus ?? 15, "Bolo máximo"),
    limits.maxBolusMin,
    limits.maxBolusMax,
    "Bolo máximo"
  );
  const roundStep = ensureRange(
    parseRequiredNumber(input.roundStep ?? 0.05, "Paso de redondeo"),
    limits.roundStepMin,
    limits.roundStepMax,
    "Paso de redondeo"
  );

  if (glucose < limits.hypoStop) {
    return {
      glucose,
      carbs,
      target,
      isf,
      icr,
      iob,
      meal: carbs / icr,
      rawCorrection: (glucose - target) / isf,
      positiveCorrection: 0,
      lowBgAdjustment: Math.min((glucose - target) / isf, 0),
      correctionAfterIob: 0,
      rawTotal: 0,
      roundedTotal: 0,
      total: 0,
      hardStop: true,
      clamped: false,
      warning: "Glucosa por debajo de 70 mg/dL: no se recomienda insulina desde la calculadora de emergencia.",
    };
  }

  const meal = carbs / icr;
  const rawCorrection = (glucose - target) / isf;
  const positiveCorrection = Math.max(rawCorrection, 0);
  const lowBgAdjustment = Math.min(rawCorrection, 0);
  const correctionAfterIob = Math.max(positiveCorrection - iob, 0);
  const rawTotal = Math.max(0, meal + lowBgAdjustment + correctionAfterIob);
  const roundedTotal = Math.max(0, roundToStep(rawTotal, roundStep));
  const total = Math.min(roundedTotal, maxBolus);

  return {
    glucose,
    carbs,
    target,
    isf,
    icr,
    iob,
    meal,
    rawCorrection,
    positiveCorrection,
    lowBgAdjustment,
    correctionAfterIob,
    rawTotal,
    roundedTotal,
    total,
    hardStop: false,
    clamped: total < roundedTotal,
    warning: total < roundedTotal ? `Dosis limitada al máximo manual de ${maxBolus.toFixed(2)} U.` : null,
  };
}
