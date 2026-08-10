import assert from 'node:assert/strict';
import {
  buildOnlineBolusPayload,
  containsClientDosingConfig,
} from '../src/lib/onlineBolusPayload.js';

const payload = buildOnlineBolusPayload({
  carbsG: 20,
  fatG: 10,
  proteinG: 15,
  fiberG: 4,
  bgMgdl: 145,
  mealSlot: 'lunch',
  carbProfile: 'med',
  alcohol: false,
  exercise: { planned: true, minutes: 45, intensity: 'moderate' },
});

assert.equal(payload.carbs_g, 20);
assert.equal(payload.bg_mgdl, 145);
assert.equal(payload.meal_slot, 'lunch');
assert.equal(payload.exercise.minutes, 45);
assert.equal(containsClientDosingConfig(payload), false);
assert.equal(Object.hasOwn(payload, 'enable_autosens'), false);

for (const forbidden of [
  'cr_g_per_u', 'isf_mgdl_per_u', 'target_mgdl', 'dia_hours',
  'insulin_model', 'round_step_u', 'max_bolus_u', 'max_correction_u',
  'warsaw_safety_factor', 'fiber_factor',
]) {
  assert.equal(Object.hasOwn(payload, forbidden), false, `${forbidden} must stay server-side`);
}

const autosensOff = buildOnlineBolusPayload({
  carbsG: 0,
  bgMgdl: 160,
  mealSlot: 'dinner',
  autosensOverride: false,
});
assert.equal(autosensOff.enable_autosens, false);
assert.equal(containsClientDosingConfig(autosensOff), false);

const autosensOn = buildOnlineBolusPayload({
  carbsG: 0,
  bgMgdl: 160,
  mealSlot: 'dinner',
  autosensOverride: true,
});
assert.equal(autosensOn.enable_autosens, true);

console.log('onlineBolusPayload tests passed');
