import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/pages/BolusPage.jsx', import.meta.url), 'utf8');

assert.match(source, /no descuenta HC nuevos/i);
assert.doesNotMatch(source, />Se restará del bolo</i);

console.log('iobUiCopy tests passed');
