import assert from 'node:assert/strict';
import { calculateManualBolus } from '../src/lib/manualBolusCore.js';

function calc(overrides = {}) {
  return calculateManualBolus({
    glucose: 110,
    carbs: 20,
    target: 110,
    isf: 30,
    icr: 10,
    iob: 0,
    maxBolus: 15,
    roundStep: 0.05,
    ...overrides,
  });
}

assert.equal(calc().total, 2);

const withIob = calc({ iob: 3.5 });
assert.equal(withIob.meal, 2);
assert.equal(withIob.correctionAfterIob, 0);
assert.equal(withIob.total, 2, 'IOB must not consume new-carb coverage');

const mealAndCorrection = calc({ glucose: 170, iob: 1 });
assert.equal(mealAndCorrection.meal, 2);
assert.equal(mealAndCorrection.positiveCorrection, 2);
assert.equal(mealAndCorrection.correctionAfterIob, 1);
assert.equal(mealAndCorrection.total, 3);

const correctionCovered = calc({ glucose: 170, carbs: 0, iob: 3.5 });
assert.equal(correctionCovered.total, 0, 'IOB must still prevent correction stacking');

const lowAdjustment = calc({ glucose: 80, iob: 3.5 });
assert.equal(lowAdjustment.lowBgAdjustment, -1);
assert.equal(lowAdjustment.total, 1);

const hypo = calc({ glucose: 65 });
assert.equal(hypo.hardStop, true);
assert.equal(hypo.total, 0);

assert.throws(() => calc({ glucose: 0 }), /Glucosa debe estar entre 40 y 400/);
assert.throws(() => calc({ glucose: Infinity }), /Glucosa debe ser un número finito/);
assert.throws(() => calc({ iob: '' }), /IOB es obligatorio/);
assert.throws(() => calc({ carbs: 501 }), /Hidratos nuevos debe estar entre 0 y 500/);

const clamped = calc({ glucose: 300, carbs: 300, maxBolus: 10 });
assert.equal(clamped.total, 10);
assert.equal(clamped.clamped, true);

console.log('manualBolusCore tests passed');
