import assert from 'node:assert/strict';
import fs from 'node:fs';

const page = fs.readFileSync(new URL('../src/pages/BolusPage.jsx', import.meta.url), 'utf8');
const hook = fs.readFileSync(new URL('../src/hooks/useBolusCalculator.js', import.meta.url), 'utf8');
const resultView = fs.readFileSync(new URL('../src/components/bolus/ResultView.jsx', import.meta.url), 'utf8');
const store = fs.readFileSync(new URL('../src/modules/core/store.js', import.meta.url), 'utf8');

assert.match(page, /Iniciar comida larga \/ buffet/);
assert.match(page, /Añadir este plato y calcular/);
assert.match(page, /HC platos/);
assert.match(page, /HC en bolos/);
assert.match(page, /Autosens se aplica desde el backend cuando esté activo/);
assert.match(page, /disabled=\{!!mealSession\}/);
assert.match(page, /setPendingMealSessionPlate\(null\)/);
assert.match(page, /setDualEnabled\(!!getSplitSettings\(\)\?\.enabled_default\)/);
assert.doesNotMatch(page, /setDualEnabled\(false\);\s*resetMealContext\(\)/);

assert.match(hook, /const apiRes = await saveTreatment\(treatment\);/);
assert.match(hook, /await addMealSessionCarbs\(mealSessionId, mealSessionPlatePayload\)/);
assert.match(hook, /await linkTreatmentToMealSession\(mealSessionId, apiRes\.treatment_id\)/);
assert.ok(
  hook.indexOf('const apiRes = await saveTreatment(treatment);') < hook.indexOf('await addMealSessionCarbs(mealSessionId, mealSessionPlatePayload)'),
  'meal ledger must be updated only after treatment save',
);
assert.ok(
  hook.indexOf('const apiRes = await saveTreatment(treatment);') < hook.indexOf('await linkTreatmentToMealSession(mealSessionId, apiRes.treatment_id)'),
  'treatment link must happen only after treatment save',
);

assert.match(resultView, /await onSave\(finalDose, injectionSite\)/);

// Execute the real getSplitSettings body with a stale legacy localStorage
// value and a newer server-synchronized value. The synchronized backend copy
// must win so an old browser cannot silently re-enable dual delivery.
const splitStart = store.indexOf('export function getSplitSettings()');
const splitEnd = store.indexOf('export function saveSplitSettings', splitStart);
assert.ok(splitStart >= 0 && splitEnd > splitStart, 'getSplitSettings source must be present');
const splitSource = store.slice(splitStart, splitEnd).replace('export ', '');
const makeGetSplitSettings = new Function(
  'localStorage',
  'getCalcParams',
  `${splitSource}; return getSplitSettings;`,
);
const storage = new Map([
  ['bolusai_split_settings', JSON.stringify({ enabled_default: true, percent_now: 90 })],
]);
const localStorageStub = { getItem: (key) => storage.get(key) ?? null };
const synchronizedServerSettings = {
  dual_bolus: {
    enabled_default: false,
    percent_now: 70,
    duration_minutes: 120,
    later_after_minutes: 120,
  },
  round_step_u: 0.5,
};
const getSplitSettings = makeGetSplitSettings(
  localStorageStub,
  () => synchronizedServerSettings,
);
const effectiveSplit = getSplitSettings();
assert.equal(effectiveSplit.enabled_default, false);
assert.equal(effectiveSplit.percent_now, 70);
assert.equal(effectiveSplit.round_step_u, 0.5);

console.log('mealSessionUiContract tests passed');
