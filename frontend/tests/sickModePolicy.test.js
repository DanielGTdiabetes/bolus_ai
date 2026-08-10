import assert from 'node:assert/strict';
import { resolveSickModeDosingPolicy } from '../src/lib/sickModePolicy.js';

const normal = resolveSickModeDosingPolicy({ icr: 10, isf: 30, isSick: false });
assert.equal(normal.icr, 10);
assert.equal(normal.isf, 30);
assert.equal(normal.active, false);
assert.equal(normal.automaticDoseAdjustment, false);
assert.equal(normal.warning, null);

const sick = resolveSickModeDosingPolicy({ icr: 10, isf: 30, isSick: true });
assert.equal(sick.icr, 10);
assert.equal(sick.isf, 30);
assert.equal(sick.active, true);
assert.equal(sick.automaticDoseAdjustment, false);
assert.match(sick.warning, /ajuste automático de dosis desactivado/i);
assert.doesNotMatch(sick.warning, /20%|aumentada/i);

assert.throws(
  () => resolveSickModeDosingPolicy({ icr: 0, isf: 30, isSick: true }),
  /ICR inválido/
);
assert.throws(
  () => resolveSickModeDosingPolicy({ icr: 10, isf: Number.POSITIVE_INFINITY, isSick: true }),
  /ISF inválido/
);

console.log('sickModePolicy tests passed');
