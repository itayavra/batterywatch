// Decode the single-value tuples printed by `gdbus call` for our providers.
// Supported: strings, booleans, finite numbers, arrays, string-key dictionaries,
// variants, scalar type annotations, @as and @a{sv}. Other syntax is rejected.
// This is a reply reader, not a complete implementation of GVariant type inference.
// One cursor advances through the input; no searching/backtracking over suffixes.
// Spec: https://docs.gtk.org/glib/gvariant-text-format.html

function parseReply(stdout) {
    if (typeof stdout !== "string")
        throw new SyntaxError("GVariant: expected reply text");

    let position = 0;
    const maxDepth = 64;
    const escapes = { a: "\x07", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t", v: "\v" };
    const integerRanges = {
        byte: [0, 255],
        int16: [-32768, 32767],
        uint16: [0, 65535],
        int32: [-2147483648, 2147483647],
        uint32: [0, 4294967295],
        // JS cannot represent every 64-bit integer exactly. Reject precision loss.
        int64: [-9007199254740991, 9007199254740991],
        uint64: [0, 9007199254740991],
        handle: [-2147483648, 2147483647]
    };
    const typeCodes = {
        "@s": "string", "@b": "boolean", "@d": "double",
        "@y": "byte", "@n": "int16", "@q": "uint16",
        "@i": "int32", "@u": "uint32", "@x": "int64",
        "@t": "uint64", "@h": "handle"
    };

    function fail(message) {
        throw new SyntaxError("GVariant at position " + position + ": " + message);
    }

    function skipWhitespace() {
        while (position < stdout.length && /\s/.test(stdout[position]))
            position++;
    }

    function expect(character) {
        skipWhitespace();
        if (stdout[position] !== character)
            fail("expected '" + character + "'");
        position++;
    }

    function readString() {
        const quote = stdout[position++];
        const parts = [];
        while (position < stdout.length) {
            let character = stdout[position++];
            if (character === quote)
                return parts.join("");
            if (character === "\0")
                fail("NUL is not allowed in strings");
            if (character !== "\\") {
                parts.push(character);
                continue;
            }
            if (position === stdout.length)
                fail("incomplete escape");
            character = stdout[position++];
            if (character === "\n")
                continue; // Escaped newline is a GVariant line continuation.
            if (character === "u" || character === "U") {
                const width = character === "u" ? 4 : 8;
                const digits = stdout.slice(position, position + width);
                if (digits.length !== width || !/^[0-9a-fA-F]+$/.test(digits))
                    fail("invalid Unicode escape");
                const point = parseInt(digits, 16);
                if (point === 0 || point > 0x10ffff || (point >= 0xd800 && point <= 0xdfff))
                    fail("invalid Unicode code point");
                parts.push(String.fromCodePoint(point));
                position += width;
            } else {
                // Other escaped characters are copied literally by GVariant.
                if (character === "\0") fail("NUL is not allowed in strings");
                parts.push(Object.prototype.hasOwnProperty.call(escapes, character) ? escapes[character] : character);
            }
        }
        fail("unterminated string");
    }

    function readArray(depth) {
        expect("[");
        const values = [];
        skipWhitespace();
        while (stdout[position] !== "]") {
            values.push(readValue(depth + 1));
            skipWhitespace();
            if (stdout[position] === "]") break;
            expect(",");
            skipWhitespace();
        }
        expect("]");
        return values;
    }

    function readDictionary(depth) {
        expect("{");
        const values = Object.create(null);
        skipWhitespace();
        while (stdout[position] !== "}") {
            if (stdout[position] !== "'" && stdout[position] !== '"')
                fail("expected a quoted dictionary key");
            const key = readString();
            if (Object.prototype.hasOwnProperty.call(values, key))
                fail("duplicate dictionary key");
            expect(":");
            values[key] = readValue(depth + 1);
            skipWhitespace();
            if (stdout[position] === "}") break;
            expect(",");
            skipWhitespace();
        }
        expect("}");
        return values;
    }

    function readNumber(token) {
        // Both patterns are anchored to the complete token, with disjoint parts.
        if (!/^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/.test(token)
                && !/^0x[0-9a-fA-F]+$/.test(token))
            fail("unsupported token or number");
        const value = Number(token);
        if (!Number.isFinite(value)) fail("non-finite number");
        const floatingPoint = !token.startsWith("0x") && /[.eE]/.test(token);
        if (!floatingPoint && !Number.isSafeInteger(value))
            fail("integer exceeds JavaScript's exact range");
        return value;
    }

    function readAnnotated(type, depth) {
        const value = readValue(depth + 1);
        if (type === "@as") {
            if (!Array.isArray(value) || !value.every(item => typeof item === "string"))
                fail("expected a string array");
        } else if (type === "@a{sv}") {
            if (!value || typeof value !== "object" || Array.isArray(value))
                fail("expected a dictionary");
        } else if (type === "string" || type === "boolean") {
            if (typeof value !== type) fail("expected " + type);
        } else if (type === "double") {
            if (typeof value !== "number") fail("expected a number");
        } else {
            const range = integerRanges[type];
            if (!Number.isSafeInteger(value) || value < range[0] || value > range[1])
                fail("integer outside " + type + " range");
        }
        return value;
    }

    function readValue(depth) {
        if (depth > maxDepth) fail("maximum nesting depth exceeded");
        skipWhitespace();
        const character = stdout[position];
        if (character === "'" || character === '"') return readString();
        if (character === "[") return readArray(depth);
        if (character === "{") return readDictionary(depth);
        if (character === "<") {
            position++;
            const value = readValue(depth + 1);
            expect(">");
            return value;
        }

        const start = position;
        if (character === "@") {
            // A type annotation ends at whitespace (its signature may contain {}).
            while (position < stdout.length && !/\s/.test(stdout[position])) position++;
        } else {
            while (position < stdout.length && !/[\s()[\]{}<>,:'"]/.test(stdout[position])) position++;
        }
        const token = stdout.slice(start, position);
        if (!token) fail("expected a value");
        if (token === "true") return true;
        if (token === "false") return false;
        const type = Object.prototype.hasOwnProperty.call(typeCodes, token) ? typeCodes[token] : token;
        if (type === "@as" || type === "@a{sv}" || type === "string" || type === "boolean"
                || type === "double" || Object.prototype.hasOwnProperty.call(integerRanges, type))
            return readAnnotated(type, depth);
        return readNumber(token);
    }

    expect("(");
    const value = readValue(0);
    expect(",");
    expect(")");
    skipWhitespace();
    if (position !== stdout.length) fail("unexpected text after reply");
    return value;
}
