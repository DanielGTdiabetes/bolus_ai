import assert from 'node:assert/strict';
import fs from 'node:fs';

const page = fs.readFileSync(new URL('../src/pages/BolusPage.jsx', import.meta.url), 'utf8');
const hook = fs.readFileSync(new URL('../src/hooks/useBolusCalculator.js', import.meta.url), 'utf8');
const resultView = fs.readFileSync(new URL('../src/components/bolus/ResultView.jsx', import.meta.url), 'utf8');

assert.match(page, /Iniciar comida larga \/ buffet/);
assert.match(page, /Añadir este plato y calcular/);
assert.match(page, /HC platos/);
assert.match(page, /HC en bolos/);
assert.match(page, /Autosens se aplica desde el backend cuando esté activo/);
assert.match(page, /disabled=\{!!mealSession\}/);
assert.match(page, /setPendingMealSessionPlate\(null\)/);

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

console.log('mealSessionUiContract tests passed');
