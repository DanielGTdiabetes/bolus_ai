import assert from 'node:assert/strict';
import { buildClientBolusTrace } from '../src/lib/bolusTrace.js';

const trace = buildClientBolusTrace({
  kind: 'normal',
  upfront_u: 2,
  later_u: 0,
  duration_min: 0,
  calc: {
    total_u_final: 2,
    total_u_raw: 2,
    meal_bolus_u: 2,
    correction_u: 0,
    iob_u: 3.5,
    iob_applied_to_correction_u: 0,
    glucose: {
      mgdl: 110,
      trend: 'Flat',
      source: 'g7_direct_watch',
      age_minutes: 2,
      is_stale: false,
    },
    used_params: {
      cr_g_per_u: 10,
      isf_mgdl_per_u: 30,
      effective_cr_g_per_u: 9.52,
      effective_isf_mgdl_per_u: 28.57,
      autosens_ratio: 1.05,
      autosens_reason: 'hybrid',
      config_hash: 'abc123',
    },
    warnings: [],
    assumptions: [],
    explain: ['A) Comida: 2.00 U'],
  },
}, 1.5, 'app');

assert.equal(trace.snapshot.recommended_u, 2);
assert.equal(trace.snapshot.accepted_u, 1.5);
assert.equal(trace.snapshot.iob_u, 3.5);
assert.equal(trace.snapshot.iob_applied_to_correction_u, 0);
assert.equal(trace.applied_ratios.autosens_ratio, 1.05);
assert.equal(trace.applied_ratios.effective_cr_g_per_u, 9.52);
assert.equal(trace.applied_ratios.effective_isf_mgdl_per_u, 28.57);
assert.equal(trace.context.bg, 110);
assert.equal(trace.context.glucose_source, 'g7_direct_watch');
assert.equal(JSON.stringify(trace).includes('token'), false);

console.log('bolusTrace tests passed');
