import assert from 'node:assert/strict';
import { glucoseFreshness, subscribeGlucoseResume } from '../src/lib/glucoseFreshness.js';

const receivedAt = Date.UTC(2026, 8, 26, 10, 45);
const reading = {
    date: receivedAt - 2 * 60000,
    age_minutes: 2,
    status: 'ok',
    usable_for_dosing: true,
};
assert.deepEqual(glucoseFreshness(reading, receivedAt, receivedAt), { ageMinutes: 2, stale: false });
// No successful request is needed for an old reading to expire on screen.
assert.deepEqual(glucoseFreshness(reading, receivedAt, receivedAt + 15 * 60000), { ageMinutes: 17, stale: true });
assert.equal(glucoseFreshness(reading, receivedAt, receivedAt, true).stale, true);
assert.equal(glucoseFreshness(reading, receivedAt, receivedAt, false).stale, false);
assert.equal(glucoseFreshness({ ...reading, status: 'conflict' }, receivedAt, receivedAt).stale, true);
assert.equal(glucoseFreshness({ ...reading, usable_for_dosing: false }, receivedAt, receivedAt).stale, true);
assert.equal(glucoseFreshness({ ...reading, date: null, age_minutes: null }, receivedAt, receivedAt).stale, true);
assert.equal(glucoseFreshness({ ...reading, date: receivedAt + 5 * 60000 }, receivedAt, receivedAt).stale, true);
// The phone clock cannot make a server-reported old sample look younger.
assert.equal(glucoseFreshness({ ...reading, age_minutes: 20 }, receivedAt, receivedAt).ageMinutes, 20);

const windowObj = new EventTarget();
const documentObj = new EventTarget();
documentObj.visibilityState = 'visible';
let refreshes = 0;
const unsubscribe = subscribeGlucoseResume(() => refreshes++, windowObj, documentObj);
for (const type of ['online', 'focus', 'pageshow', 'bolusai:resume']) windowObj.dispatchEvent(new Event(type));
documentObj.dispatchEvent(new Event('visibilitychange'));
assert.equal(refreshes, 5);
documentObj.visibilityState = 'hidden';
windowObj.dispatchEvent(new Event('focus'));
documentObj.dispatchEvent(new Event('visibilitychange'));
assert.equal(refreshes, 5);
documentObj.visibilityState = 'visible';
documentObj.dispatchEvent(new Event('visibilitychange'));
assert.equal(refreshes, 6);
unsubscribe();
windowObj.dispatchEvent(new Event('bolusai:resume'));
documentObj.dispatchEvent(new Event('visibilitychange'));
assert.equal(refreshes, 6);
console.log('Glucose freshness and resume tests passed');
