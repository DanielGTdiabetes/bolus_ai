import assert from 'node:assert/strict';
import {
  calculateCoveredCarbsForIngestion,
  calculateNewCarbsToCover,
  isLinkedToIngestion,
  parseCoveredCarbs,
} from '../src/lib/orphanCarbsCore.js';

assert.equal(parseCoveredCarbs('BolusAI: Normal. Gr: 40 (Sincronizado). [linked_ingestion_id=meal-1]'), 40);
assert.equal(parseCoveredCarbs('[covered_carbs=20.5] [linked_ingestion_id=meal-1]'), 20.5);
assert.equal(parseCoveredCarbs('sin datos'), null);

const treatments = [
  {
    id: 'b1',
    carbs: 0,
    notes: 'BolusAI: Normal. Gr: 40 (Sincronizado). [linked_ingestion_id=meal-1]',
  },
  {
    id: 'b2',
    carbs: 0,
    notes: 'BolusAI: Normal. Gr: 15 (Sincronizado). [linked_ingestion_id=meal-2]',
  },
  {
    id: 'b3',
    carbs: 0,
    notes: 'BolusAI: Normal. Gr: 10 (Sincronizado). [linked_ingestion_id=meal-1]',
  },
];

assert.equal(isLinkedToIngestion(treatments[0], 'meal-1'), true);
assert.equal(isLinkedToIngestion(treatments[1], 'meal-1'), false);
assert.equal(calculateCoveredCarbsForIngestion(treatments, 'meal-1'), 50);
assert.equal(calculateCoveredCarbsForIngestion(treatments, 'meal-2'), 15);

// Critical regression: external meal grows from 40 g to 60 g.
// Only +20 g must be offered as new carbs.
assert.equal(calculateNewCarbsToCover(60, 40), 20);

// A nearby unrelated synchronized meal must not affect this ingestion.
assert.equal(calculateNewCarbsToCover(60, calculateCoveredCarbsForIngestion(treatments, 'meal-2')), 45);

assert.equal(calculateNewCarbsToCover(40, 40), 0);
assert.equal(calculateNewCarbsToCover(38, 40), 0);
assert.throws(() => calculateNewCarbsToCover(Infinity, 0));

console.log('orphanCarbsCore tests passed');
