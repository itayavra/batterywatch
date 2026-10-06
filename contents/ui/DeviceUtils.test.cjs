// No npm dependencies. Keep beside DeviceUtils.js and run:
// node --test DeviceUtils.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, 'DeviceUtils.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(source, context);
const getIconForType = context.getIconForType;

test('legacy and canonical headset types use the headset icon', () => {
    assert.equal(getIconForType('headset'), 'audio-headset');
    assert.equal(getIconForType('audio-headset'), 'audio-headset');
});

test('legacy and canonical headphones types use the headphones icon', () => {
    assert.equal(getIconForType('headphones'), 'audio-headphones');
    assert.equal(getIconForType('audio-headphones'), 'audio-headphones');
});
