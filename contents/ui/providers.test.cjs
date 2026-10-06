// Executes the onNewData handlers from the provider QML files with the QML
// scope stubbed, so the code under test is the code that ships.
// Keep beside the providers and run: node --test providers.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'GVariant.js'), 'utf8'), context);
const GVariant = { parseReply: context.parseReply };
vm.runInContext(fs.readFileSync(path.join(__dirname, 'DeviceUtils.js'), 'utf8'), context);
const DeviceUtils = {
    canonicalSerial: context.canonicalSerial,
    deviceIdentity: context.deviceIdentity,
    getIconForType: context.getIconForType
};

// Braces inside a line comment must not shift the body, so count with the
// comment removed. No handler has a "//" inside a string literal.
const braceDelta = line => {
    let delta = 0;
    for (const ch of line.replace(/\/\/.*$/, '')) {
        if (ch === '{') delta++;
        else if (ch === '}') delta--;
    }
    return delta;
};

// Shared brace-balanced block scanner: from the line that opens a block, the
// body lines (dedented by `dedent` spaces) and the line index that closes it.
const blockAt = (lines, open, dedent) => {
    const body = [];
    let depth = 1;
    let close = open;
    for (let j = open + 1; depth > 0 && j < lines.length; j++) {
        depth += braceDelta(lines[j]);
        if (depth === 0) { close = j; break; }
        body.push(dedent ? lines[j].replace(new RegExp(`^ {${dedent}}`), '') : lines[j]);
    }
    assert.equal(depth, 0, `braces did not balance from line ${open + 1}`);
    return { body, close };
};

// Pull each `onNewData: (src, data) => { ... }` body out of a provider and
// compile it, so the assertions run the provider's own source. The reply
// parameter is named differently per provider, so keep the name the file
// uses; `parseUPowerOutput` and `detailsSource` are the provider methods and
// DataSource ids the UPower handlers call, and the others ignore them.
function readHandlers(file) {
    const lines = fs.readFileSync(path.join(__dirname, 'providers', file), 'utf8').split('\n');
    const found = [];
    for (let i = 0; i < lines.length; i++) {
        const opening = lines[i].match(/onNewData: \((\w+), data\) => \{/);
        if (!opening) continue;
        const block = blockAt(lines, i, 12);
        i = block.close;
        const text = block.body.join('\n');
        found.push({
            body: text,
            readsReply: text.includes('parseReply'),
            run: new Function(opening[1], 'data', 'root', 'i18n', 'Qt', 'GVariant',
                'parseUPowerOutput', 'detailsSource',
                'const disconnectSource = () => {};\n' + text)
        });
    }
    return found;
}

// Pull a named function out of a QML file, so tests can call the shipped
// source under stubbed globals. `dir` defaults to the provider directory.
function readFunction(file, name, dir = 'providers') {
    const lines = fs.readFileSync(path.join(__dirname, dir, file), 'utf8').split('\n');
    for (let i = 0; i < lines.length; i++) {
        if (!lines[i].includes(`function ${name}(`)) continue;
        return blockAt(lines, i, 0).body.join('\n');
    }
    assert.fail(`function ${name} not found in ${file}`);
}

const kde = readHandlers('KDEConnectProvider.qml');
const razer = readHandlers('OpenRazerProvider.qml');

// Key each handler by a string only it contains.
function byTag(list, tag) {
    const hits = list.filter(h => h.body.includes(tag));
    assert.equal(hits.length, 1, `expected exactly one handler containing ${JSON.stringify(tag)}`);
    return hits[0];
}

// Calls a provider's function in a context that mirrors what the QML gives it.
// Stubs are visible to the compiled code; parameters are passed at call time.
function callFunction(source, name, params, stubs, ...args) {
    const context = vm.createContext(stubs);
    vm.runInContext(`function ${name}(${params}) {\n${source}\n}`, context);
    return context[name](...args);
}

const upower = readFunction('UPowerProvider.qml', 'parseUPowerOutput');
const UPOWER_ROOT = {
    wiredType: 0, wirelessType: 1, bluetoothType: 2,
    upowerDeviceTypeOverrides: {}
};
const UPOWER_STUBS = {
    root: UPOWER_ROOT,
    DeviceUtils: { getIconForType: t => `icon(${t})` },
    i18n: s => s,
    console: { log() {}, warn() {} }
};
const parseUpower = (output, objectPath = '/test') =>
    callFunction(upower, 'parseUPowerOutput', 'output, objectPath', UPOWER_STUBS, output, objectPath);

// Real upower -i shapes from this machine's devices, trimmed to what the
// parser consumes.
const UPOWER_BT_HIDPP = ['  native-path:          hidpp_battery_2', '  model:                MX Master 3',
    '  serial:               cb:6a:b2:6c:73:47', '  mouse',
    '    percentage:          50%', '    state:               charging',
    "    icon-name:           'battery-full-charging-symbolic'"].join('\n');
const UPOWER_DONGLE_HIDPP = ['  native-path:          hidpp_battery_0', '  model:                Wireless Mouse M305',
    '  serial:               f9-0d-4f-0c', '  mouse',
    '    percentage:          89%', '    state:               discharging'].join('\n');
const UPOWER_BLUEZ = ['  native-path:          bluez:0C_1A_0F_2E_91_62',
    '  serial:               0C-1A-0F-2E-91-62', '  headphones',
    '    percentage:          70%', '    state:               discharging'].join('\n');
// Captured verbatim from a real M305 that had just been switched off. The
// node survives in `upower -e` because the Unifying receiver is still powered.
const UPOWER_HIDPP_OFF = ['  native-path:          (null)', '  power supply:         no',
    '  updated:              Thu 01 Jan 1970 02:00:00 (1791156071 seconds ago)',
    '  has history:          no', '  has statistics:       no', '  unknown',
    '    warning-level:       unknown', '    battery-level:       unknown',
    "    percentage:          0% (should be ignored)",
    "    icon-name:           '(null)'"].join('\n');
// The same device while AWAKE, captured verbatim. Note that it still carries
// "(should be ignored)" - UPower flags hidpp percentages as uncalibrated even
// for a working device (it reads 55% where Solaar reads 50%), which is why the
// suffix on its own must never be used to hide a device.
const UPOWER_HIDPP_ON = ['  native-path:          hidpp_battery_5', '  model:                Logitech M305',
    '  serial:               f9-0d-4f-0c', '  power supply:         no', '  has history:          yes',
    '  has statistics:       yes', '  mouse',
    '    present:             yes', '    rechargeable:        yes',
    '    state:               discharging', '    warning-level:       none',
    '    battery-level:       normal', "    percentage:          55% (should be ignored)",
    "    icon-name:           'battery-low-symbolic'"].join('\n');
// The other mouse on this machine, awake and fully charged, captured verbatim.
// It is Bluetooth (a colon-MAC serial), which is why it disappears on its own
// when switched off. It also carries "(should be ignored)" at a healthy 100% -
// proof that the suffix says nothing about a device being off.
const UPOWER_MXMASTER = ['  native-path:          hidpp_battery_7', '  model:                MX Master 3',
    '  serial:               cb:6a:b2:6c:73:47', '  power supply:         no',
    '  has history:          yes', '  has statistics:       yes', '  mouse',
    '    present:             yes', '    rechargeable:        yes',
    '    state:               fully-charged', '    warning-level:       none',
    '    battery-level:       full', "    percentage:          100% (should be ignored)",
    "    icon-name:           'battery-full-charged-symbolic'"].join('\n');

// The command line each DataSource is started with; the handlers read the
// device id out of it and ignore a src that does not carry one.
const SRC = {
    kdeList: '/usr/bin/gdbus call --session -d org.kde.kdeconnect -o /modules/kdeconnect -m org.kde.kdeconnect.daemon ListDevices',
    kdeId: id => `/usr/bin/gdbus call --session -d org.kde.kdeconnect -o /modules/kdeconnect -m org.kde.kdeconnect.device /devices/${id} org.kde.kdeconnect.device.GetAll`,
    razerList: '/usr/bin/openrazer-daemon --list-devices',
    razerId: (id, call) => `/usr/bin/openrazer-daemon --device 0x1533 0x1D5C 0x0265 /device/${id} ${call}`
};

const SEED = () => ({
    deviceData: { AAA: { name: 'Kept', battery: 42, charging: true }, BBB: { name: 'B', battery: 1, charging: false } },
    knownDevices: { AAA: true, BBB: true },
    devices: [], daemonUnavailable: false, kdeConnectEnabled: true, razerEnabled: true,
    fetchDeviceData() {}, refreshBattery() {}, fetchNameAndType() {}, fetchPowerInfo() {}
});

// Pass `root` to keep one provider state across replies, so a handler that
// damages it is visible to the next call.
function fire(handler, { reply, src, seed = SEED(), code = 0, stderr = '', root = null,
    parse = null, sources = null }) {
    root = root || Object.assign(SEED(), seed);
    const warnings = [];
    const i18n = (s, a) => s.replace('%1', a === undefined ? '' : a);
    let scheduled = 0;
    const Qt = { callLater() { scheduled++; }, refresh() { scheduled++; } };
    const realWarn = console.warn;
    const realLog = console.log;
    console.warn = m => warnings.push(m);
    console.log = () => {};
    let threw = null;
    try {
        handler.run(src, { ['exit code']: code, stdout: reply, stderr }, root, i18n, Qt, GVariant,
            parse, sources);
    } catch (error) {
        threw = error;
    }
    console.warn = realWarn;
    console.log = realLog;
    return { root, warnings, scheduled, threw };
}

// A reply the provider is meant to accept must not throw either.
function fireOk(handler, options) {
    const r = fire(handler, options);
    assert.equal(r.threw, null, `unexpected throw: ${r.threw && r.threw.message}`);
    return r;
}

// Replies that do not parse, and replies that parse into the wrong shape or
// the wrong type for the call that produced them.
const UNPARSEABLE = ['', null, 'nonsense', "(['aaa',", '()', '@as []', "'aaa'", '([', "({'a': <1>,}"];
const NOT_ARRAY = ["('aaa', 'bbb',)", "([['aaa', 'bbb']],)", '(1,)', "('aaa',)"];
const NOT_DICT = ['([],)', '(1,)', "('aaa',)", '(nan,)'];
const NOT_NUMBER = ["('88',)", '(nan,)', '(inf,)', '(true,)'];
const NOT_BOOL = ['(1,)', "('true',)"];
const NOT_STRING = ['(1,)', '(nan,)'];

const PARSING = [
    { name: 'KDE Connect device list', tag: 'expected an array of device ids',
      bad: [...UNPARSEABLE, ...NOT_ARRAY] },
    { name: 'KDE Connect properties', tag: "expected 'name' to be a string",
      bad: [...UNPARSEABLE, ...NOT_DICT, "({'name': <1>,},)", "({'type': <1>,},)"] },
    { name: 'KDE Connect battery', tag: "expected 'isCharging' to be a boolean",
      bad: [...UNPARSEABLE, ...NOT_DICT, "({'charge': <'x'>,},)", "({'isCharging': <1>,},)"] },
    { name: 'OpenRazer device list', tag: 'expected an array of device ids',
      bad: [...UNPARSEABLE, ...NOT_ARRAY] },
    { name: 'OpenRazer battery', tag: 'expected a finite number',
      bad: [...UNPARSEABLE, ...NOT_NUMBER] },
    { name: 'OpenRazer charging', tag: 'expected a boolean',
      bad: [...UNPARSEABLE, ...NOT_BOOL] },
    { name: 'OpenRazer details', tag: 'expected a string',
      bad: [...UNPARSEABLE, ...NOT_STRING] }
];

// What each handler must leave alone when it refuses a reply.
const UNCHANGED = {
    'KDE Connect device list': root => {
        assert.deepEqual(Object.keys(root.knownDevices), ['AAA', 'BBB']);
        assert.deepEqual(Object.keys(root.deviceData), ['AAA', 'BBB']);
    },
    'KDE Connect properties': root => {
        assert.equal(root.deviceData.AAA.name, 'Kept');
        assert.equal(root.deviceData.AAA.type, 'phone');
    },
    'KDE Connect battery': root => {
        assert.equal(root.deviceData.AAA.charge, 42);
        assert.equal(root.deviceData.AAA.charging, false);
    },
    'OpenRazer device list': root => {
        assert.deepEqual(Object.keys(root.knownDevices), ['AAA', 'BBB']);
        assert.deepEqual(Object.keys(root.deviceData), ['AAA', 'BBB']);
    },
    'OpenRazer battery': root => assert.equal(root.deviceData.AAA.battery, 42),
    'OpenRazer charging': root => assert.equal(root.deviceData.AAA.charging, true),
    'OpenRazer details': root => assert.equal(root.deviceData.AAA.name, 'Kept')
};

const SRC_FOR = {
    'KDE Connect device list': () => SRC.kdeList,
    'KDE Connect properties': () => SRC.kdeId('AAA'),
    'KDE Connect battery': () => SRC.kdeId('AAA'),
    'OpenRazer device list': () => SRC.razerList,
    'OpenRazer battery': () => SRC.razerId('AAA', 'misc.getBattery'),
    'OpenRazer charging': () => SRC.razerId('AAA', 'misc.getCharging'),
    'OpenRazer details': () => SRC.razerId('AAA', 'misc.getDeviceName')
};

const handlerFor = name => {
    const spec = PARSING.find(p => p.name === name);
    const list = name.startsWith('KDE') ? kde : razer;
    return byTag(list, spec.tag);
};

const SEED_FOR = {
    'KDE Connect properties': { deviceData: { AAA: { name: 'Kept', type: 'phone' } } },
    'KDE Connect battery': { deviceData: { AAA: { charge: 42, charging: false } } },
    'OpenRazer battery': { deviceData: { AAA: { battery: 42 } } },
    'OpenRazer charging': { deviceData: { AAA: { charging: true } } },
    'OpenRazer details': { deviceData: { AAA: { name: 'Kept' } } }
};

test('every provider handler is found and compiled', () => {
    assert.equal(kde.length, 4, 'KDE Connect DataSource count changed');
    assert.equal(razer.length, 4, 'OpenRazer DataSource count changed');
    const parsing = [...kde, ...razer].filter(h => h.readsReply);
    assert.equal(parsing.length, 7, 'a handler stopped reading a reply through GVariant');
    for (const spec of PARSING) byTag(spec.name.startsWith('KDE') ? kde : razer, spec.tag);
});

test('a refused reply never throws, never changes device data, never refreshes', () => {
    for (const spec of PARSING) {
        const handler = handlerFor(spec.name);
        for (const reply of spec.bad) {
            const label = `${spec.name} ${JSON.stringify(reply)}`;
            const r = fire(handler, { reply, src: SRC_FOR[spec.name](), seed: SEED_FOR[spec.name] });
            assert.equal(r.threw, null, `${label} threw`);
            assert.equal(r.warnings.length, 1, `${label} was not reported exactly once`);
            assert.equal(r.scheduled, 0, `${label} scheduled a refresh`);
            UNCHANGED[spec.name](r.root);
        }
    }
});

test('a valid reply is applied', () => {
    let r = fireOk(handlerFor('KDE Connect device list'), { reply: "(['id1', 'id2'],)", src: SRC.kdeList, seed: { deviceData: {}, knownDevices: {} } });
    assert.deepEqual(Object.keys(r.root.knownDevices), ['id1', 'id2']);

    r = fireOk(handlerFor('KDE Connect properties'), {
        reply: `({'name': <"Bob's Phone">, 'type': <'phone'>,},)`, src: SRC.kdeId('id1'),
        seed: { deviceData: { id1: { name: '', type: '' } } }
    });
    assert.equal(r.root.deviceData.id1.name, "Bob's Phone");
    assert.equal(r.root.deviceData.id1.type, 'phone');

    r = fireOk(handlerFor('KDE Connect battery'), {
        reply: "({'charge': <75>, 'isCharging': <false>},)", src: SRC.kdeId('id1'),
        seed: { deviceData: { id1: { charge: -1, charging: true } } }
    });
    assert.equal(r.root.deviceData.id1.charge, 75);
    assert.equal(r.root.deviceData.id1.charging, false);

    r = fireOk(handlerFor('OpenRazer device list'), { reply: "(['AAA', 'BBB'],)", src: SRC.razerList, seed: { deviceData: {}, knownDevices: {} } });
    assert.deepEqual(Object.keys(r.root.knownDevices), ['AAA', 'BBB']);

    r = fireOk(handlerFor('OpenRazer battery'), { reply: '(85.0,)', src: SRC.razerId('AAA', 'misc.getBattery'), seed: { deviceData: { AAA: { battery: 0 } } } });
    assert.equal(r.root.deviceData.AAA.battery, 85);

    r = fireOk(handlerFor('OpenRazer charging'), { reply: '(true,)', src: SRC.razerId('AAA', 'misc.getCharging'), seed: { deviceData: { AAA: { charging: false } } } });
    assert.equal(r.root.deviceData.AAA.charging, true);

    r = fireOk(handlerFor('OpenRazer details'), { reply: `(<"Razer Viper's Pro">,)`, src: SRC.razerId('AAA', 'misc.getDeviceName'), seed: { deviceData: { AAA: { name: '' } } } });
    assert.equal(r.root.deviceData.AAA.name, "Razer Viper's Pro");
});

test('a missing property keeps its previous value', () => {
    let r = fireOk(handlerFor('KDE Connect properties'), {
        reply: "({'name': <'Renamed'>,},)", src: SRC.kdeId('AAA'),
        seed: { deviceData: { AAA: { name: 'Kept', type: 'phone' } } }
    });
    assert.equal(r.root.deviceData.AAA.name, 'Renamed');
    assert.equal(r.root.deviceData.AAA.type, 'phone');

    r = fireOk(handlerFor('KDE Connect battery'), {
        reply: "({'isCharging': <true>,},)", src: SRC.kdeId('AAA'),
        seed: { deviceData: { AAA: { charge: 42, charging: false } } }
    });
    assert.equal(r.root.deviceData.AAA.charge, 42);
    assert.equal(r.root.deviceData.AAA.charging, true);
});

test('an empty device list disconnects the devices', () => {
    const r = fireOk(handlerFor('OpenRazer device list'), { reply: '(@as [],)', src: SRC.razerList });
    assert.deepEqual(Object.keys(r.root.knownDevices), []);
    assert.deepEqual(Object.keys(r.root.deviceData), []);
    assert.equal(r.scheduled, 1);
});

test('a refused device list leaves polling enabled and does not stop the next poll', () => {
    for (const [name, enabled] of [
        ['KDE Connect device list', 'kdeConnectEnabled'],
        ['OpenRazer device list', 'razerEnabled']
    ]) {
        const handler = handlerFor(name);
        const src = SRC_FOR[name]();
        const root = Object.assign(SEED(), { knownDevices: { AAA: true, BBB: true } });

        // One state, carried across every reply, so a handler that leaves
        // polling disabled or the daemon flagged is caught here.
        for (const bad of ['', "([['AAA', 'BBB']],)", 'nonsense']) {
            const r = fire(handler, { reply: bad, src, root });
            assert.equal(r.threw, null, `${name} threw on ${JSON.stringify(bad)}`);
            assert.equal(r.root[enabled], true, `${name} disabled polling on ${JSON.stringify(bad)}`);
            assert.equal(r.root.daemonUnavailable, false, `${name} flagged the daemon on ${JSON.stringify(bad)}`);
            assert.deepEqual(Object.keys(r.root.knownDevices), ['AAA', 'BBB'], `${name} pruned devices on ${JSON.stringify(bad)}`);
        }

        const r = fire(handler, { reply: "(['AAA'],)", src, root });
        assert.equal(r.threw, null, `${name} threw on the valid reply`);
        assert.equal(r.root[enabled], true, `${name} disabled polling on the valid reply`);
        assert.deepEqual(Object.keys(r.root.knownDevices), ['AAA'], `${name} did not apply the valid reply`);
        assert.deepEqual(Object.keys(r.root.deviceData), ['AAA'], `${name} did not prune the stale device`);
        assert.equal(r.scheduled, 1);
    }
});

test('a failed command is not reported as an unreadable reply', () => {
    for (const name of PARSING.map(p => p.name)) {
        const r = fire(handlerFor(name), {
            reply: '', src: SRC_FOR[name](), seed: SEED_FOR[name], code: 1, stderr: 'no such device'
        });
        assert.equal(r.threw, null, `${name} threw`);
        assert.deepEqual(r.warnings, [], `${name} reported a command failure as a parse failure`);
    }
});

test('an OpenRazer device without a battery is dropped', () => {
    const r = fireOk(handlerFor('OpenRazer battery'), {
        reply: '', src: SRC.razerId('AAA', 'misc.getBattery'),
        seed: { deviceData: { AAA: { battery: 42 } } }, code: 1, stderr: 'Error UnknownMethod misc.getBattery'
    });
    assert.equal(r.root.deviceData.AAA, undefined);
    assert.equal(r.scheduled, 1);
});

test('unpairing refreshes without reading a reply', () => {
    const handler = byTag(kde, 'Qt.callLater(root.refresh)');
    assert.equal(handler.readsReply, false);
    const r = fireOk(handler, { reply: '', src: '/usr/bin/gdbus call --session -d org.kde.kdeconnect' });
    assert.equal(r.scheduled, 1);
    assert.deepEqual(r.warnings, []);
});

// ══════════════════════════════════════════════════════════════════════════
// UPower output parsing (pure function; covers the hidpp transport fix)
// ══════════════════════════════════════════════════════════════════════════

test('upower parses device fields, type and charging', () => {
    const d = parseUpower(UPOWER_BT_HIDPP, '/org/freedesktop/UPower/devices/battery_hidpp_battery_2');
    assert.equal(d.name, 'MX Master 3');
    assert.equal(d.serial, 'cb:6a:b2:6c:73:47');
    assert.equal(d.percentage, 50);
    assert.equal(d.charging, true);            // from state: and icon-name:
    assert.equal(d.type, 'mouse');
    assert.equal(d.objectPath, '/org/freedesktop/UPower/devices/battery_hidpp_battery_2');
    assert.equal(d.icon, 'icon(mouse)');
});

test('a hidpp battery reporting a colon-MAC serial is Bluetooth', () => {
    // Kernel hidpp batteries carry the transport in the serial; the BT link
    // exposes the peer MAC. This case must keep its disconnect action.
    const d = parseUpower(UPOWER_BT_HIDPP);
    assert.equal(d.connectionType, 2);
    assert.equal(d.bluetoothAddress, 'CB:6A:B2:6C:73:47');
    assert.equal(typeof d.disconnect, 'function');
});

test('a hidpp battery over a receiver or cable stays wireless (regression)', () => {
    // The real M305 behind a Unifying receiver reports a dash-separated uniq.
    // Regression 1: when the MAC match fails, classification must still land
    // on wireless (1) - not the wired default (0), which the provider silently
    // drops, hiding the device entirely.
    const d = parseUpower(UPOWER_DONGLE_HIDPP);
    assert.equal(d.connectionType, 1, 'dongle hidpp battery was not classified wireless');
    // Regression 2 (same fixture): without a MAC there is no disconnect
    // action and no bluetooth address
    assert.equal(d.bluetoothAddress, '');
    assert.equal(d.disconnect, undefined);
    assert.equal(d.percentage, 89);
});

test('bluez devices classify Bluetooth via the native-path as before', () => {
    const d = parseUpower(UPOWER_BLUEZ);
    assert.equal(d.connectionType, 2);
    assert.equal(d.bluetoothAddress, '0C:1A:0F:2E:91:62');
    assert.equal(d.type, 'headphones');
});

// ══════════════════════════════════════════════════════════════════════════
// Stale HID++ nodes: a device that is switched off keeps its battery node
// while the receiver is powered, so the list has to drop it on battery-level
// ══════════════════════════════════════════════════════════════════════════

test('a switched-off receiver device parses as unknown with a misleading 0%', () => {
    // The trap this guards: "0% (should be ignored)" parses to 0, and the
    // provider's percentage >= 0 gate accepts 0, so the device used to sit in
    // the list at 0% forever. The two flags below are what reveal it is off.
    const d = parseUpower(UPOWER_HIDPP_OFF);
    assert.equal(d.batteryLevel, 'unknown');
    assert.equal(d.percentageIgnored, true);
    assert.equal(d.percentage, 0, 'documents the misleading parse this fixes');
    assert.equal(d.charging, false);
});

test('a stale cached percentage is still recognised as untrustworthy', () => {
    // The real symptom was not a stable 0%: with history enabled UPower serves
    // the last awake reading, so the device was pinned at 50% while off. The
    // stale reading must be caught whatever number it carries.
    const stale = UPOWER_HIDPP_OFF.replace('0% (should be ignored)', '50% (should be ignored)')
        .replace('  native-path:          (null)', '  native-path:          hidpp_battery_5')
        .replace('  has history:          no', '  has history:          yes');
    const d = parseUpower(stale);
    assert.equal(d.percentage, 50, 'the stale number is what UPower reports');
    assert.equal(d.batteryLevel, 'unknown');
    assert.equal(d.percentageIgnored, true, 'but it is flagged as untrustworthy');
});

test('a real battery level is parsed and is not mistaken for unknown', () => {
    // Regression: a genuinely empty battery reports "empty", not "unknown",
    // and a trusted percentage with no "(should be ignored)" suffix, so the
    // fix above must not hide real flat batteries.
    const out = UPOWER_DONGLE_HIDPP + '\n    battery-level:       low';
    const d = parseUpower(out);
    assert.equal(d.batteryLevel, 'low');
    assert.equal(d.percentageIgnored, false);
    assert.equal(d.percentage, 89);
});

test('an unknown level without the ignored marker is kept', () => {
    // Deliberately conservative: only the combination of both signals means
    // "there is no battery reading", so an odd device is never silently lost.
    const d = parseUpower(UPOWER_DONGLE_HIDPP + '\n    battery-level:       unknown');
    assert.equal(d.batteryLevel, 'unknown');
    assert.equal(d.percentageIgnored, false);
    assert.equal(d.percentage, 89, 'still shown');
});

test('upower removes a device once its battery level goes unknown', () => {
    // The receiver keeps the node enumerated, so the list reply cannot drop
    // it - only the detail reply reveals the device is off.
    const path = '/org/freedesktop/UPower/devices/battery_hidpp_battery_5';
    const live = parseUpower(UPOWER_DONGLE_HIDPP, path);
    const root = upowerRoot(true, [live, { objectPath: '/other', name: 'Keep me' }]);
    const r = fireOk(upowerDetails, { reply: UPOWER_HIDPP_OFF, src: `/usr/bin/upower -i ${path}`, root, parse: parseUpower });
    assert.deepEqual(r.root.devices.map(d => d.name), ['Keep me'],
        'the switched-off device was not removed');
});

test('upower still adds a device that was unknown and came back', () => {
    // It must reappear once it wakes, so the removal is not a one-way door.
    const path = '/org/freedesktop/UPower/devices/battery_hidpp_battery_5';
    const root = upowerRoot(true, []);
    const r = fireOk(upowerDetails, { reply: UPOWER_DONGLE_HIDPP, src: `/usr/bin/upower -i ${path}`, root, parse: parseUpower });
    assert.equal(r.root.devices.length, 1);
    assert.equal(r.root.devices[0].name, 'Wireless Mouse M305');
});

test('removing a device leaves its detail source polling so it can return', () => {
    // No `sources`: a handler that disconnected the poll here would be unable
    // to notice the device coming back.
    const path = '/org/freedesktop/UPower/devices/battery_hidpp_battery_5';
    const root = upowerRoot(true, [parseUpower(UPOWER_DONGLE_HIDPP, path)]);
    fireOk(upowerDetails, { reply: UPOWER_HIDPP_OFF, src: `/usr/bin/upower -i ${path}`, root, parse: parseUpower });
    assert.deepEqual(root.devices, []);
});

test('the same device is kept while awake, though it is still marked ignored', () => {
    // The regression that shaped the rule: real UPower output for a WORKING
    // M305 also says "(should be ignored)". Filtering on that suffix alone
    // would hide a live, discharging mouse. Only the pairing with
    // battery-level "unknown" means the device is actually off.
    const path = '/org/freedesktop/UPower/devices/battery_hidpp_battery_5';
    const parsed = parseUpower(UPOWER_HIDPP_ON, '/x');
    assert.equal(parsed.batteryLevel, 'normal');
    assert.equal(parsed.percentageIgnored, true, 'the suffix is present even when awake');
    const root = upowerRoot(true, []);
    const r = fireOk(upowerDetails, { reply: UPOWER_HIDPP_ON, src: `/usr/bin/upower -i ${path}`, root, parse: parseUpower });
    assert.equal(r.root.devices.length, 1, 'the awake device was hidden');
    assert.equal(r.root.devices[0].percentage, 55);
});

test('off and on replies drive the same device in and out of the list', () => {
    // End-to-end on the two real captures: switching the mouse off must remove
    // it, switching it on must bring the very same device back.
    const path = '/org/freedesktop/UPower/devices/battery_hidpp_battery_5';
    const src = `/usr/bin/upower -i ${path}`;
    const root = upowerRoot(true, []);

    const on = fireOk(upowerDetails, { reply: UPOWER_HIDPP_ON, src, root, parse: parseUpower });
    assert.equal(on.root.devices.length, 1);
    assert.equal(on.root.devices[0].name, 'Logitech M305');

    const off = fireOk(upowerDetails, { reply: UPOWER_HIDPP_OFF, src, root, parse: parseUpower });
    assert.deepEqual(off.root.devices.map(d => d.name), [], 'stayed in the list after power-off');

    const back = fireOk(upowerDetails, { reply: UPOWER_HIDPP_ON, src, root, parse: parseUpower });
    assert.equal(back.root.devices.length, 1, 'did not come back after power-on');
    assert.equal(back.root.devices[0].percentage, 55);
});

test('a healthy full-charge device marked ignored is still kept', () => {
    // The second mouse on this machine, awake at 100%. It carries the same
    // "(should be ignored)" suffix as the off M305, so any rule that dropped on
    // the suffix alone would have hidden a fully charged mouse. This is the
    // regression that pins the rule to battery-level.
    const path = '/org/freedesktop/UPower/devices/battery_hidpp_battery_7';
    const root = upowerRoot(true, []);
    const r = fireOk(upowerDetails, { reply: UPOWER_MXMASTER, src: `/usr/bin/upower -i ${path}`, root, parse: parseUpower });
    assert.equal(r.root.devices.length, 1, 'a full-charge device was hidden');
    assert.equal(r.root.devices[0].percentage, 100);
    assert.equal(r.root.devices[0].batteryLevel, 'full');
    assert.equal(r.root.devices[0].percentageIgnored, true);
    assert.equal(r.root.devices[0].connectionType, 2, 'still classified Bluetooth');
    assert.equal(r.root.devices[0].bluetoothAddress, 'CB:6A:B2:6C:73:47');
});

test('only an unknown level is dropped, on both real mice', () => {
    // Summary of the rule against every real reading captured from this
    // machine: only the off M305 combines an unknown level with the marker.
    const cases = [
        ['M305 off', UPOWER_HIDPP_OFF, true],
        ['M305 on', UPOWER_HIDPP_ON, false],
        ['MX Master on', UPOWER_MXMASTER, false],
    ];
    for (const [label, out, dropped] of cases) {
        const d = parseUpower(out);
        assert.equal(d.batteryLevel === 'unknown' && d.percentageIgnored, dropped, label);
    }
});

// ══════════════════════════════════════════════════════════════════════════
// UPower enable switch (enableUPowerIntegration)
// ══════════════════════════════════════════════════════════════════════════
const upowerHandlers = readHandlers('UPowerProvider.qml');
const upowerList = byTag(upowerHandlers, 'foundPaths');
const upowerDetails = byTag(upowerHandlers, 'parseUPowerOutput');

const UPOWER_BT_PATH = '/org/freedesktop/UPower/devices/battery_hidpp_battery_2';
const UPOWER_LIST_SRC = '/usr/bin/upower -e';
const UPOWER_DETAIL_SRC = `/usr/bin/upower -i ${UPOWER_BT_PATH}`;
const upowerRoot = (enabled, devices = []) => Object.assign(SEED(), { upowerEnabled: enabled, devices });

test('upower asks for details of an unknown device while enabled', () => {
    const connected = [];
    const sources = { connectSource: src => connected.push(src), disconnectSource() {} };
    const r = fireOk(upowerList, { reply: UPOWER_BT_PATH + '\n', src: UPOWER_LIST_SRC, root: upowerRoot(true), sources });
    assert.deepEqual(connected, ['upower -i ' + UPOWER_BT_PATH]);
    assert.deepEqual(r.root.devices, [], 'the list reply adds no devices by itself');
});

test('upower reads a detail reply into a device while enabled', () => {
    const r = fireOk(upowerDetails, { reply: UPOWER_BT_HIDPP, src: UPOWER_DETAIL_SRC, root: upowerRoot(true), parse: parseUpower });
    assert.equal(r.root.devices.length, 1);
    assert.equal(r.root.devices[0].name, 'MX Master 3');
    assert.equal(r.root.devices[0].connectionType, 2);
});

test('upower drops its devices and ignores a list reply once disabled', () => {
    const root = upowerRoot(false, [{ objectPath: UPOWER_BT_PATH }]);
    // No `sources`: a handler that kept running would call detailsSource here.
    const r = fireOk(upowerList, { reply: UPOWER_BT_PATH + '\n', src: UPOWER_LIST_SRC, root });
    assert.deepEqual(r.root.devices, [], 'devices survived the provider being disabled');
});

test('a detail reply arriving after disabling is discarded', () => {
    const root = upowerRoot(false, [{ objectPath: UPOWER_BT_PATH, serial: 'cb:6a:b2:6c:73:47' }]);
    const r = fireOk(upowerDetails, { reply: UPOWER_BT_HIDPP, src: UPOWER_DETAIL_SRC, root, parse: parseUpower });
    assert.deepEqual(r.root.devices, [], 'a late detail reply re-populated the disabled provider');
});

// ══════════════════════════════════════════════════════════════════════════
// Load-time structure
// ══════════════════════════════════════════════════════════════════════════

test('every provider that uses Plasmoid imports the plasmoid module', () => {
    // Plasmoid is a singleton from org.kde.plasma.plasmoid, not a context
    // property, so a file that reads it without the import throws
    // "ReferenceError: Plasmoid is not defined" the moment the applet loads -
    // and the handler tests never see it, because they stub `root`. That is
    // how UPower's enable switch ended up silently disabling the whole
    // provider: every binding, timer and handler keyed off a false value.
    const dir = path.join(__dirname, 'providers');
    const files = fs.readdirSync(dir).filter(f => f.endsWith('.qml'));
    assert.ok(files.length >= 6, `expected the provider set, found ${files.length}`);
    for (const file of files) {
        const source = fs.readFileSync(path.join(dir, file), 'utf8');
        if (!/\bPlasmoid\./.test(source)) continue;
        assert.match(source, /^import org\.kde\.plasma\.plasmoid/m,
            `${file} uses Plasmoid but does not import org.kde.plasma.plasmoid`);
    }
});

// ══════════════════════════════════════════════════════════════════════════
// Cross-provider merging (main.qml)
// ══════════════════════════════════════════════════════════════════════════

const mergeDevices = readFunction('main.qml', 'mergeDevices', '.');
const merge = (...providers) =>
    callFunction(mergeDevices, 'mergeDevices', 'deviceProviders', { DeviceUtils }, providers);
// Loads the hidden list the way the applet does on startup, from the raw
// strings Plasmoid.configuration holds.
// The applet's own loadHiddenDevices, with the assignment it makes to the
// hidden list landing on the vm context instead of a QML property.
const loadHidden = saved => {
    const context = vm.createContext({
        Plasmoid: { configuration: { hiddenDevices: saved } },
        i18n: s => s,
        DeviceUtils
    });
    vm.runInContext(`function loadHiddenDevices() {\n${readFunction('main.qml', 'loadHiddenDevices', '.')}\n}`, context);
    context.loadHiddenDevices();
    return context.hiddenDevices;
};
// Providers build these themselves; only the fields mergeDevices reads matter.
const fromUpower = (serial, name) => ({ serial, name, source: 'upower' });
const fromSolaar = (serial, name) => ({ serial, name, source: 'solaar' });

test('the same receiver unit in two spellings merges into one device', () => {
    // UPower echoes the kernel's HID_UNIQ; Solaar reports the HID++ unit
    // serial. Without a canonical key the mouse is listed twice.
    const merged = merge([fromUpower('f9-0d-4f-0c', 'Wireless Mouse M305')],
        [fromSolaar('F90D4F0C', 'M305')]);
    assert.equal(merged.length, 1, 'the mouse was listed twice');
    assert.equal(merged[0].source, 'upower', 'the higher-priority provider should win');
});

test('a Bluetooth MAC merges regardless of case', () => {
    const merged = merge([fromUpower('cb:6a:b2:6c:73:47', 'MX Master 3')],
        [fromSolaar('CB:6A:B2:6C:73:47', 'MX Master 3 Wireless Mouse')]);
    assert.equal(merged.length, 1);
});

test('different devices stay separate', () => {
    const merged = merge([fromUpower('f9-0d-4f-0c', 'Wireless Mouse M305')],
        [fromSolaar('E4B786D0', 'MX Master 3'), fromSolaar('F90D4F0C', 'M305')]);
    assert.equal(merged.length, 2, 'distinct devices collapsed into one');
});

test('a descriptor serial is not treated as byte separators', () => {
    // 4066-C535 is the kernel's name for a headset, not a byte string, so it
    // must not become 4066C535 and merge with a device that reports that.
    const merged = merge([fromUpower('4066-C535', 'G533')],
        [fromSolaar('4066C535', 'G533 Gaming Headset')]);
    assert.equal(merged.length, 2, 'a named serial was collapsed by normalization');
});

test('devices without a serial fall back to their object path', () => {
    const a = { serial: '', objectPath: '/org/freedesktop/UPower/devices/battery_hidpp_battery_2', name: 'A' };
    const b = { serial: '', objectPath: '/org/freedesktop/UPower/devices/battery_hidpp_battery_3', name: 'B' };
    const merged = merge([a], [b]);
    assert.equal(merged.length, 2);
    // The array comes from the vm realm, so compare elements, not prototypes.
    assert.equal(merged[0].name, 'A');
    assert.equal(merged[1].name, 'B');
});

test('canonicalSerial keeps unusable input harmless', () => {
    assert.equal(DeviceUtils.canonicalSerial(undefined), '');
    assert.equal(DeviceUtils.canonicalSerial(''), '');
    assert.equal(DeviceUtils.canonicalSerial(null), '');
    assert.equal(DeviceUtils.canonicalSerial(12345), '');
});

test('a hidden device stays hidden when a provider spells its serial differently', () => {
    // Hidden while UPower reported the kernel HID_UNIQ; Solaar is now the only
    // source and reports the HID++ unit serial for the same mouse.
    const hidden = loadHidden('f9-0d-4f-0c');
    const fromSolaar = { serial: 'F90D4F0C', name: 'Wireless Mouse M305' };
    assert.notEqual(hidden.indexOf(DeviceUtils.deviceIdentity(fromSolaar)), -1,
        'the device came back after its provider changed the spelling');
});

test('the hidden list canonicalises every entry already stored', () => {
    const hidden = loadHidden('f9-0d-4f-0c,4066-C535,cb:6a:b2:6c:73:47');
    assert.equal(hidden.length, 3);
    assert.equal(hidden[0], 'F90D4F0C');
    assert.equal(hidden[1], '4066-C535');
    assert.equal(hidden[2], 'CB6AB26C7347');
});

test('hiding a device without a serial does not hide the other ones', () => {
    const a = { serial: '', objectPath: '/org/freedesktop/UPower/devices/line_power_AC' };
    const b = { serial: '', objectPath: '/org/freedesktop/UPower/devices/battery_hidpp_battery_2' };
    const hidden = loadHidden(DeviceUtils.deviceIdentity(a));
    assert.equal(hidden.length, 1);
    assert.equal(hidden.indexOf(DeviceUtils.deviceIdentity(b)), -1,
        'every device without a serial would have been hidden together');
});

test('deviceIdentity prefers the serial, then the object path', () => {
    assert.equal(DeviceUtils.deviceIdentity({ serial: 'f9-0d-4f-0c' }), 'F90D4F0C');
    assert.equal(DeviceUtils.deviceIdentity({ serial: '', objectPath: '/org/x' }), '/org/x');
    assert.equal(DeviceUtils.deviceIdentity({}), '');
    assert.equal(DeviceUtils.deviceIdentity(null), '');
});
