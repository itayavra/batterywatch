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

// Arrays built inside the vm context have another realm's prototype; copy them out for deepEqual.
const mergeDevices = (...args) => Array.from(context.mergeDevices(...args));
const dev = (serial, name, extra = {}) => ({ serial, name, percentage: 50, ...extra });

test('mergeDevices returns an empty list for no providers or empty providers', () => {
    assert.deepEqual(mergeDevices([]), []);
    assert.deepEqual(mergeDevices([[], []]), []);
});

test('mergeDevices sorts by name and treats a missing name as empty', () => {
    const merged = mergeDevices([[dev('c', 'Zed'), dev('a', 'Alpha'), dev('b', undefined)]]);
    assert.deepEqual(merged.map(d => d.serial), ['b', 'a', 'c']);
});

test('mergeDevices skips devices with no identity', () => {
    const merged = mergeDevices([[{ name: 'Ghost' }, dev('a', 'Real')]]);
    assert.deepEqual(merged.map(d => d.name), ['Real']);
});

test('mergeDevices keeps the higher-priority provider entry for a duplicate', () => {
    const merged = mergeDevices([
        [dev('a', 'First', { percentage: 80 })],
        [dev('a', 'Second', { percentage: 20 })],
    ]);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].name, 'First');
    assert.equal(merged[0].percentage, 80);
});

test('mergeDevices dedupes within a single provider as well', () => {
    const merged = mergeDevices([[dev('a', 'One'), dev('a', 'Two')]]);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].name, 'One');
});

test('mergeDuplicate does not mutate its inputs when filling fields', () => {
    const winner = { serial: 'a', name: 'W', percentage: null, charging: null };
    const later = { serial: 'a', name: 'L', percentage: 40, charging: true };
    const result = context.mergeDuplicate(winner, later);
    assert.equal(result.percentage, 40);
    assert.equal(result.charging, true);
    assert.equal(winner.percentage, null);
    assert.equal(winner.charging, null);
});

// ── mergeDevices: filling gaps from later providers ──────────────────────

test('a later provider fills a missing percentage on an existing device', () => {
    const merged = mergeDevices([
        [{ serial: 'a', name: 'Mouse', percentage: null, charging: false }],
        [{ serial: 'a', name: 'Mouse', percentage: 64, charging: true }],
    ]);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].percentage, 64);
    assert.equal(merged[0].charging, false, 'a known charging state was overwritten');
});

test('a later provider fills a missing charging state on an existing device', () => {
    const merged = mergeDevices([
        [{ serial: 'a', name: 'Mouse', percentage: 40 }],
        [{ serial: 'a', name: 'Mouse', percentage: 99, charging: true }],
    ]);
    assert.equal(merged[0].percentage, 40, 'a known percentage was overwritten');
    assert.equal(merged[0].charging, true);
});

test('gaps are filled from different later providers in turn', () => {
    const merged = mergeDevices([
        [{ serial: 'a', name: 'Mouse' }],
        [{ serial: 'a', name: 'Mouse', percentage: 70 }],
        [{ serial: 'a', name: 'Mouse', percentage: 10, charging: true }],
    ]);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].percentage, 70);
    assert.equal(merged[0].charging, true);
});

test('the winner keeps its own name, icon and other fields when filled', () => {
    const merged = mergeDevices([
        [{ serial: 'a', name: 'Winner', icon: 'input-mouse', percentage: null }],
        [{ serial: 'a', name: 'Later', icon: 'other', percentage: 30 }],
    ]);
    assert.equal(merged[0].name, 'Winner');
    assert.equal(merged[0].icon, 'input-mouse');
    assert.equal(merged[0].percentage, 30);
});

test('filling matches a device across serial spellings', () => {
    const merged = mergeDevices([
        [{ serial: 'F90D4F0C', name: 'M305', percentage: null }],
        [{ serial: 'f9-0d-4f-0c', name: 'M305', percentage: 50 }],
    ]);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].percentage, 50);
});

test('filling does not modify the provider objects', () => {
    const original = { serial: 'a', name: 'Mouse', percentage: null };
    mergeDevices([[original], [{ serial: 'a', name: 'Mouse', percentage: 20 }]]);
    assert.equal(original.percentage, null);
});

test('a blocked placeholder is replaced by a later reading through mergeDevices', () => {
    const merged = mergeDevices([
        [{ serial: 'a', name: 'Blocked', blocked: true }],
        [{ serial: 'a', name: 'Readable', percentage: 55 }],
    ]);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].name, 'Readable');
    assert.notEqual(merged[0].blocked, true);
});

// ── buildTrayItems ────────────────────────────────────────────────────────

const buildTrayItems = (...args) => Array.from(context.buildTrayItems(...args));

test('buildTrayItems emits one item per single-battery device', () => {
    const items = buildTrayItems([{ serial: 'a', icon: 'i', percentage: 40, charging: true }], []);
    assert.equal(items.length, 1);
    assert.equal(items[0].percentage, 40);
    assert.equal(items[0].charging, true);
    assert.equal(items[0].label, null);
    assert.equal(items[0].deviceSerial, 'a');
});

test('buildTrayItems skips hidden and blocked devices', () => {
    const items = buildTrayItems([
        { serial: 'hidden', percentage: 1 },
        { serial: 'blocked', blocked: true },
        { serial: 'shown', percentage: 2 },
    ], ['HIDDEN']);
    assert.deepEqual(items.map(i => i.deviceSerial), ['shown']);
});

test('buildTrayItems expands multi-battery devices and honours showInTray', () => {
    const items = buildTrayItems([{ serial: 'pods', icon: 'i', batteries: [
        { label: 'Left', percentage: 50 },
        { label: 'Right', percentage: 60, charging: true },
        { label: 'Case', percentage: 90, showInTray: false },
    ] }], []);
    assert.deepEqual(items.map(i => i.label), ['Left', 'Right']);
    assert.equal(items[1].charging, true);
});

test('buildTrayItems treats a one-battery batteries array as a single device', () => {
    const items = buildTrayItems([{ serial: 'a', percentage: 33, batteries: [{ label: 'Main', percentage: 99 }] }], []);
    assert.equal(items.length, 1);
    assert.equal(items[0].percentage, 33);
});

// ── findLowBatteryAlerts ──────────────────────────────────────────────────

const lowAlerts = (devices, { muted = [], threshold = 20, notified = {} } = {}) => {
    const r = context.findLowBatteryAlerts(devices, muted, threshold, notified);
    return { alerts: Array.from(r.alerts), notified: Object.assign({}, r.notified) };
};

test('an alert is raised at or below the threshold, not above it', () => {
    assert.equal(lowAlerts([{ serial: 'a', percentage: 20 }]).alerts.length, 1);
    assert.equal(lowAlerts([{ serial: 'a', percentage: 21 }]).alerts.length, 0);
});

test('0% is ignored because devices report it when switched off', () => {
    assert.equal(lowAlerts([{ serial: 'a', percentage: 0 }]).alerts.length, 0);
});

test('devices without a usable reading raise no alert', () => {
    const r = lowAlerts([
        { serial: 'a' },
        { serial: 'b', percentage: null },
        { serial: 'c', percentage: 'abc' },
    ]);
    assert.equal(r.alerts.length, 0);
});

test('muted devices and devices with no identity raise no alert', () => {
    const r = lowAlerts([{ serial: 'a', percentage: 5 }, { name: 'ghost', percentage: 5 }], { muted: ['A'] });
    assert.equal(r.alerts.length, 0);
});

test('an alert is raised once, then again after the battery recovers', () => {
    const low = [{ serial: 'a', name: 'Mouse', percentage: 10 }];
    const first = lowAlerts(low);
    assert.equal(first.alerts.length, 1);
    assert.deepEqual({ ...first.alerts[0] }, { name: 'Mouse', label: '', percentage: 10 });

    const second = lowAlerts(low, { notified: first.notified });
    assert.equal(second.alerts.length, 0);

    const recovered = lowAlerts([{ serial: 'a', percentage: 80 }], { notified: second.notified });
    assert.deepEqual(recovered.notified, {});
    assert.equal(lowAlerts(low, { notified: recovered.notified }).alerts.length, 1);
});

test('charging batteries raise no alert and keep their notified state', () => {
    const notified = { 'A:0': true };
    const r = lowAlerts([{ serial: 'a', batteries: [{ percentage: 5, charging: true }] }], { notified });
    assert.equal(r.alerts.length, 0);
    assert.equal(r.notified['A:0'], true);
});

test('multi-battery devices alert per labelled battery', () => {
    const r = lowAlerts([{ serial: 'pods', name: 'Pods', batteries: [
        { label: 'Left', percentage: 5 },
        { label: 'Right', percentage: 50 },
    ] }]);
    assert.equal(r.alerts.length, 1);
    assert.equal(r.alerts[0].label, 'Left');
    assert.deepEqual(Object.keys(r.notified), ['PODS:Left']);
});

test('findLowBatteryAlerts does not modify the notified map it is given', () => {
    const notified = {};
    lowAlerts([{ serial: 'a', percentage: 5 }], { notified });
    assert.deepEqual(notified, {});
});

// ── validateDevice ────────────────────────────────────────────────────────

const validateDevice = device => Array.from(context.validateDevice(device));
const goodDevice = () => ({ name: 'Mouse', serial: 'a', icon: 'input-mouse', percentage: 50, charging: false });

test('validateDevice accepts a complete device', () => {
    assert.deepEqual(validateDevice(goodDevice()), []);
});

test('validateDevice accepts unknown charging, a blocked device without a reading, and an objectPath identity', () => {
    assert.deepEqual(validateDevice({ ...goodDevice(), charging: null }), []);
    assert.deepEqual(validateDevice({ name: 'HID', serial: 'x', icon: 'i', blocked: true }), []);
    assert.deepEqual(validateDevice({ ...goodDevice(), serial: '', objectPath: '/p' }), []);
    assert.deepEqual(validateDevice({ ...goodDevice(), name: '' }), []);
});

test('validateDevice reports each missing or malformed top-level field', () => {
    const cases = [
        [{ ...goodDevice(), name: undefined }, /name/],
        [{ ...goodDevice(), serial: '' }, /serial or an objectPath/],
        [{ ...goodDevice(), icon: undefined }, /icon/],
        [{ ...goodDevice(), percentage: null }, /percentage/],
        [{ ...goodDevice(), percentage: 101 }, /percentage/],
        [{ ...goodDevice(), percentage: '50' }, /percentage/],
        [{ ...goodDevice(), charging: 'yes' }, /charging/],
        [{ ...goodDevice(), batteries: 'x' }, /batteries must be an array/],
        [null, /not an object/],
    ];
    for (const [device, pattern] of cases) {
        const problems = validateDevice(device);
        assert.ok(problems.some(p => pattern.test(p)), `${JSON.stringify(device)} -> ${problems}`);
    }
});

test('validateDevice checks every battery of a multi-battery device', () => {
    const device = { name: 'Pods', serial: 'p', icon: 'i', batteries: [
        { label: 'Left', percentage: 50, charging: false },
        { percentage: 50 },
        { label: 'Case', percentage: null },
    ] };
    const problems = validateDevice(device);
    assert.equal(problems.length, 2);
    assert.ok(problems.some(p => p.includes('batteries[1] needs a label')));
    assert.ok(problems.some(p => p.includes('batteries[2].percentage')));
});

test('a multi-battery device needs no top-level percentage', () => {
    const device = { name: 'Pods', serial: 'p', icon: 'i', batteries: [{ label: 'Left', percentage: 50 }] };
    assert.deepEqual(validateDevice(device), []);
});

// ── the built-in debug devices ────────────────────────────────────────────

test('every built-in test device passes validateDevice', () => {
    const testContext = vm.createContext({});
    vm.runInContext(fs.readFileSync(path.join(__dirname, 'TestDevices.js'), 'utf8'), testContext);
    const devices = Array.from(testContext.testDevices);
    assert.ok(devices.length > 0);
    for (const device of devices) {
        assert.deepEqual(validateDevice(device), [], `test device ${device.name}`);
    }
});
