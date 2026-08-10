import assert from 'node:assert/strict';
import {
  buildMealSessionPlatePayload,
  summarizeMealSessionProgress,
} from '../src/lib/mealSessionFlow.js';

const payload = buildMealSessionPlatePayload({
  clientEventId: 'plate-0001',
  carbs: '22.5',
  mealMeta: { fat: 8, protein: 12, fiber: 3 },
  foodName: 'Segundo plato',
});

assert.deepEqual(payload, {
  client_event_id: 'plate-0001',
  carbs_g: 22.5,
  fat_g: 8,
  protein_g: 12,
  fiber_g: 3,
  label: 'Segundo plato',
  source: 'app',
});
assert.equal(payload.source, 'app');

for (const forbidden of [
  'target_mgdl', 'cr_g_per_u', 'isf_mgdl_per_u', 'dia_hours',
  'insulin_model', 'round_step_u', 'max_bolus_u', 'enable_autosens',
]) {
  assert.equal(Object.hasOwn(payload, forbidden), false, `${forbidden} must stay in central bolus engine`);
}

assert.throws(
  () => buildMealSessionPlatePayload({ carbs: 10 }),
  /identificador del plato/,
);

assert.deepEqual(
  summarizeMealSessionProgress({
    carbs_recorded_g: 45,
    carbs_submitted_for_bolus_g: 25,
    accepted_insulin_u: 3.5,
    event_count: 4,
  }),
  {
    carbsRecordedG: 45,
    carbsSubmittedForBolusG: 25,
    acceptedInsulinU: 3.5,
    eventCount: 4,
  },
);

console.log('mealSessionFlow tests passed');
