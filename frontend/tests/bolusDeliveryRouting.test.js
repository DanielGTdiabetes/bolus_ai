import assert from 'node:assert/strict';
import { resolveBackendBolusDelivery } from '../src/lib/bolusDeliveryRouting.js';

const normal = resolveBackendBolusDelivery({
  kind: 'normal',
  total_u_final: 4.0,
  upfront_u: 4.0,
  later_u: 0,
  duration_min: 0,
});
assert.equal(normal.kind, 'normal');
assert.equal(normal.upfront_u, 4.0);
assert.equal(normal.later_u, 0);

const warsawDual = resolveBackendBolusDelivery({
  kind: 'dual',
  total_u_final: 5.0,
  upfront_u: 3.5,
  later_u: 1.5,
  duration_min: 240,
});
assert.equal(warsawDual.kind, 'dual');
assert.equal(warsawDual.upfront_u, 3.5);
assert.equal(warsawDual.later_u, 1.5);
assert.equal(warsawDual.duration_min, 240);

const extended = resolveBackendBolusDelivery({
  kind: 'extended',
  total_u: 3.0,
  upfront_u: 1.0,
  later_u: 2.0,
  duration_min: 120,
});
assert.equal(extended.kind, 'extended');
assert.equal(extended.upfront_u, 1.0);
assert.equal(extended.later_u, 2.0);

const derivedUpfront = resolveBackendBolusDelivery({
  kind: 'dual',
  total_u_final: 5.0,
  later_u: 2.0,
  duration_min: 180,
});
assert.equal(derivedUpfront.upfront_u, 3.0);
assert.equal(derivedUpfront.later_u, 2.0);

const misleadingKindWithoutLater = resolveBackendBolusDelivery({
  kind: 'dual',
  total_u_final: 2.0,
  upfront_u: 2.0,
  later_u: 0,
});
assert.equal(misleadingKindWithoutLater.kind, 'normal');
assert.equal(misleadingKindWithoutLater.upfront_u, 2.0);

console.log('bolusDeliveryRouting tests passed');
