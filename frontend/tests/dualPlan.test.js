import assert from 'node:assert/strict';
import {
  buildPersistentDualPlan,
  getAuthoritativeBolusTotal,
} from '../src/lib/dualPlan.js';

const clientDual = {
  kind: 'dual',
  calc: {
    total_u_final: 6,
    used_params: { meal_slot: 'dinner' },
  },
  plan: {
    plan_id: 'plan-123',
    mode: 'dual',
    total_recommended_u: 6,
    now_u: 4,
    later_u_planned: 2,
    later_after_min: 90,
    extended_duration_min: 120,
  },
  upfront_u: 4,
  later_u: 2,
  duration_min: 120,
};

const normalizedClient = buildPersistentDualPlan({
  result: clientDual,
  treatmentId: 'tx-123',
  acceptedUpfrontU: 3.5,
  createdAtTs: 1000,
  mealSlot: 'dinner',
});

assert.equal(getAuthoritativeBolusTotal(clientDual), 6);
assert.equal(normalizedClient.id, 'plan-123');
assert.equal(normalizedClient.treatment_id, 'tx-123');
assert.equal(normalizedClient.total_recommended_u, 6);
assert.equal(normalizedClient.upfront_u, 3.5);
assert.equal(normalizedClient.later_u_planned, 2);
assert.equal(normalizedClient.later_after_min, 90);
assert.equal(normalizedClient.extended_duration_min, 120);
assert.equal(normalizedClient.meal_slot, 'dinner');

const warsawDual = {
  kind: 'dual',
  calc: {
    total_u_final: 5.5,
    upfront_u: 4,
    later_u: 1.5,
    duration_min: 180,
    used_params: { meal_slot: 'lunch' },
  },
  upfront_u: 4,
  later_u: 1.5,
  duration_min: 180,
};

const normalizedWarsaw = buildPersistentDualPlan({
  result: warsawDual,
  treatmentId: 'tx-warsaw',
  acceptedUpfrontU: 4,
  createdAtTs: 2000,
  mealSlot: 'lunch',
  source: 'app-warsaw',
});

assert.equal(getAuthoritativeBolusTotal(warsawDual), 5.5);
assert.equal(normalizedWarsaw.id, 'tx-warsaw');
assert.equal(normalizedWarsaw.plan_id, 'tx-warsaw');
assert.equal(normalizedWarsaw.total_recommended_u, 5.5);
assert.equal(normalizedWarsaw.upfront_u, 4);
assert.equal(normalizedWarsaw.later_u_planned, 1.5);
assert.equal(normalizedWarsaw.later_after_min, 180);
assert.equal(normalizedWarsaw.extended_duration_min, 180);
assert.equal(normalizedWarsaw.source, 'app-warsaw');

assert.throws(
  () => buildPersistentDualPlan({ result: warsawDual, acceptedUpfrontU: 4 }),
  /identificador estable/,
);

console.log('dualPlan tests passed');
