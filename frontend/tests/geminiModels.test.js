import assert from 'node:assert/strict';
import { migrateGeminiSettings } from '../src/lib/geminiModels.js';

const old = { lunch: { icr: 12 }, custom: { preserved: true }, vision: {
    gemini_model: 'gemini-2.5-flash', gemini_transcribe_model: 'models/gemini-2.0-flash-exp',
    gemini_key: 'test-only', provider: 'gemini',
} };
const migrated = migrateGeminiSettings(old);
assert.equal(migrated.vision.gemini_model, 'gemini-3.5-flash-lite');
assert.equal(migrated.vision.gemini_transcribe_model, 'gemini-3.5-flash-lite');
assert.equal(old.vision.gemini_model, 'gemini-2.5-flash');
assert.deepEqual(migrated.lunch, old.lunch);
assert.deepEqual(migrated.custom, old.custom);
assert.equal(migrated.vision.gemini_key, old.vision.gemini_key);
assert.deepEqual(migrateGeminiSettings(migrated), migrated);
assert.equal(migrateGeminiSettings(null), null);
assert.deepEqual(migrateGeminiSettings({}), {});
assert.equal(migrateGeminiSettings({ vision: { gemini_model: 'custom-model' } }).vision.gemini_model, 'custom-model');
console.log('Gemini saved settings migration passed');
