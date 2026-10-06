// No npm dependencies. Keep beside GVariant.js and run:
// node --test GVariant.test.cjs
// The providers that call it are covered by providers.test.cjs.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, 'GVariant.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(source, context);
const parseReply = context.parseReply;
// Normalize cross-realm objects for value comparisons. Test prototypes separately.
const plain = value => JSON.parse(JSON.stringify(value));

const valid = [
    ['serial string', "('0669ad21f1a31aa1efb78f18b8b23647',)", '0669ad21f1a31aa1efb78f18b8b23647'],
    ['device list', "(['id1', 'id2'],)\n", ['id1', 'id2']],
    ['bus names', "(['org.freedesktop.DBus', ':1.0'],)", ['org.freedesktop.DBus', ':1.0']],
    ['empty typed array', '(@as [],)', []],
    ['empty typed dictionary', '(@a{sv} {},)', {}],
    ['apostrophe', `({'name': <"Bob's Phone">, 'type': <'phone'>},)`, { name: "Bob's Phone", type: 'phone' }],
    ['greater-than in name', "({'name': <'My > Phone'>},)", { name: 'My > Phone' }],
    ['property syntax inside name', `({'name': <"'type': <'tablet'>">, 'type': <'phone'>},)`, { name: "'type': <'tablet'>", type: 'phone' }],
    ['battery properties', "({'charge': <75>, 'isCharging': <false>},)", { charge: 75, isCharging: false }],
    ['unknown charge', "({'charge': <-1>, 'isCharging': <true>},)", { charge: -1, isCharging: true }],
    ['empty string', "('',)", ''],
    ['empty property', "({'name': <''>},)", { name: '' }],
    ['escaped apostrophe', String.raw`('it\'s',)`, "it's"],
    ['escaped double quote', String.raw`("a\"b",)`, 'a"b'],
    ['backslash', String.raw`('C:\\Devices',)`, 'C:\\Devices'],
    ['literal slash-n versus newline', String.raw`('a\\nb\nc',)`, 'a\\nb\nc'],
    ['control escapes', String.raw`('\a\b\f\n\r\t\v',)`, '\x07\b\f\n\r\t\v'],
    ['Unicode escapes', String.raw`('\u263a \U0001f600',)`, '☺ 😀'],
    ['literal Unicode', "('טלפון 😀',)", 'טלפון 😀'],
    ['other escaped character', String.raw`('a\qb',)`, 'aqb'],
    ['line continuation', "('a\\\nb',)", 'ab'],
    ['integer', '(85,)', 85],
    ['double', '(75.0,)', 75],
    ['exponent', '(1.25e+2,)', 125],
    ['true', '(true,)', true],
    ['false', '(false,)', false],
    ['byte hex', '(byte 0xff,)', 255],
    ['int16 minimum', '(int16 -32768,)', -32768],
    ['uint16 maximum', '(uint16 65535,)', 65535],
    ['int32 minimum', '(int32 -2147483648,)', -2147483648],
    ['uint32 maximum', '(uint32 4294967295,)', 4294967295],
    ['small uint64', '(uint64 42,)', 42],
    ['safe int64 limit', '(int64 9007199254740991,)', 9007199254740991],
    ['typed string', '(string "name",)', 'name'],
    ['typed boolean', '(boolean true,)', true],
    ['typed double', '(double 75.0,)', 75],
    ['type code', '(@i 7,)', 7],
    ['type code boolean', '(@b false,)', false],
    ['populated annotated array', "(@as ['a', 'b'],)", ['a', 'b']],
    ['populated annotated dictionary', "(@a{sv} {'a': <1>},)", { a: 1 }],
    ['nested values', "({'nested': <{'list': <['>', '<']>}>},)", { nested: { list: ['>', '<'] } }],
    ['array trailing comma', '([1, 2,],)', [1, 2]],
    ['dictionary trailing comma', "({'x': <1>,},)", { x: 1 }],
    ['outer whitespace', '  ( [] , ) \n', []],
    ['64 nested variants', '(' + '<'.repeat(64) + '1' + '>'.repeat(64) + ',)', 1]
];

for (const [name, input, expected] of valid) {
    test(name, () => assert.deepEqual(plain(parseReply(input)), expected));
}

const invalid = [
    ['undefined', undefined], ['null', null], ['non-string', 3], ['empty stdout', ''],
    ['empty tuple', '()'], ['missing tuple comma', '(1)'],
    ['multiple return values', "('x', 'y',)"], ['nested tuple', "(('a','b'),)"],
    ['trailing content', '(1,) junk'], ['missing tuple end', '(1,'],
    ['unclosed quote', "('unterminated,)"], ['incomplete escape', "('a\\"],
    ['bad Unicode digits', String.raw`('\uZZZZ',)`],
    ['short Unicode escape', String.raw`('\u12',)`],
    ['out-of-range Unicode', String.raw`('\U00110000',)`],
    ['high surrogate', String.raw`('\uD800',)`],
    ['low surrogate', String.raw`('\uDC00',)`],
    ['escaped NUL', String.raw`('\u0000',)`], ['literal NUL', "('a\0b',)"],
    ['missing array comma', '([1 2],)'], ['wrong closing bracket', '([1, 2},)'],
    ['missing variant end', "({'x': <1},)"],
    ['missing property colon', "({'x' <1>},)"],
    ['non-string dictionary key', '({1: <2>},)'],
    ['duplicate dictionary key', "({'x': <1>, 'x': <2>},)"],
    ['nan', '(nan,)'], ['inf', '(inf,)'], ['negative inf', '(-inf,)'],
    ['overflow', '(1e999,)'], ['numeric suffix', '(12junk,)'],
    ['unsafe bare integer', '(9007199254740992,)'],
    ['unsafe uint64', '(uint64 18446744073709551615,)'],
    ['negative uint64', '(uint64 -1,)'], ['byte overflow', '(byte 256,)'],
    ['int16 overflow', '(int16 32768,)'], ['non-integral int32', '(int32 1.5,)'],
    ['wrong string-array element', '(@as [1],)'],
    ['wrong dictionary annotation', '(@a{sv} [],)'],
    ['wrong string value', '(string 4,)'], ['wrong boolean value', '(boolean 1,)'],
    ['wrong double value', '(double true,)'],
    ['maybe value unsupported', '(just 1,)'], ['nothing unsupported', '(nothing,)'],
    ['bytestring unsupported', '(b"bytes",)'], ['array type unsupported', '(@ai [],)'],
    // This reader accepts the whitespace-separated annotations gdbus emits,
    // not every spelling accepted by GLib's general-purpose text parser.
    ['annotation requires whitespace', "(@a{sv}{'a': <1>},)"],
    ['array annotation requires whitespace', '(@as[],)'],
    ['65 nested variants', '(' + '<'.repeat(65) + '1' + '>'.repeat(65) + ',)']
];

for (const [name, input] of invalid) {
    test('rejects ' + name, () => {
        assert.throws(() => parseReply(input), error => error.name === 'SyntaxError');
    });
}

test('dictionary keys cannot modify the object prototype', () => {
    const result = parseReply("({'__proto__': <'data'>, 'constructor': <'also data'>},)");
    assert.equal(Object.getPrototypeOf(result), null);
    assert.equal(result.__proto__, 'data');
    assert.equal(result.constructor, 'also data');
    assert.equal(result.hasOwnProperty, undefined);
    assert.equal(Object.prototype.hasOwnProperty.call(result, '__proto__'), true);
    assert.equal(Object.prototype.hasOwnProperty.call(result, 'missing'), false);
});

test('a malformed later property rejects the whole reply', () => {
    assert.throws(() => parseReply("({'name': <'Valid'>, 'charge': <nan>},)"),
        error => error.name === 'SyntaxError');
});

test('failure does not contaminate a subsequent parse', () => {
    assert.throws(() => parseReply(''), error => error.name === 'SyntaxError');
    assert.deepEqual(plain(parseReply("(['recovered'],)")), ['recovered']);
});

test('long valid backslash runs and names parse without backtracking', () => {
    const local = vm.createContext({ input: "('" + '\\\\'.repeat(40000) + "',)" });
    vm.runInContext(source, local);
    assert.equal(vm.runInContext('parseReply(input)', local, { timeout: 2000 }), '\\'.repeat(40000));
});

test('large unterminated escaped-quote input fails without global-regex rescanning', () => {
    const local = vm.createContext({ input: "('" + "\\'".repeat(80000) });
    vm.runInContext(source, local);
    // vm's execution watchdog also stops synchronous runaway regexes. A timeout
    // is an Error, not SyntaxError, so it fails this regression test.
    assert.throws(() => vm.runInContext('parseReply(input)', local, { timeout: 2000 }),
        error => error.name === 'SyntaxError');
});
