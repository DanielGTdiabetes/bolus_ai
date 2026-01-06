import assert from "assert";
import { buildHistoryFromSnapshot, shouldDegradeSimulation } from "../src/pages/bolusSimulationUtils.js";

const now = new Date("2025-01-01T12:00:00Z");

const iobData = {
  breakdown: [
    { ts: "2025-01-01T11:00:00Z", units: 1.0, duration: 0 },
    { ts: "2025-01-01T10:00:00Z", units: 0.5, duration: 30 },
  ],
};

const treatments = [
  { created_at: "2025-01-01T10:30:00Z", carbs: 20, fat: 5, protein: 10, fiber: 3, insulin: 0.5 },
  { created_at: "2025-01-01T09:45:00Z", carbs: 0, fat: 0, protein: 0, fiber: 12, insulin: 0 },
];

const events = buildHistoryFromSnapshot(iobData, treatments, now);

assert(events.boluses.length >= 3, "Debe incluir bolos históricos y actuales");
assert(events.carbs.some((c) => c.grams === 20), "Debe incluir evento de carbohidratos con macros");
assert(events.carbs.some((c) => c.fiber_g === 12), "Debe permitir eventos solo fibra");

assert.strictEqual(shouldDegradeSimulation("unavailable", "ok"), true);
assert.strictEqual(shouldDegradeSimulation("ok", "stale"), true);
assert.strictEqual(shouldDegradeSimulation("ok", "ok"), false);

console.log("simulation payload tests passed");
