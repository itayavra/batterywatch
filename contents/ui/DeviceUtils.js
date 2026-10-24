
// Shared device utilities

// Serials for one physical device arrive in different shapes: the HID++ unit
// serial Solaar reports (F90D4F0C), the kernel's HID_UNIQ which UPower echoes
// in the serial field for the same receiver unit (f9-0d-4f-0c), and a
// Bluetooth MAC (cb:6a:b2:6c:73:47). Reduce those to one key so two providers
// listing the same mouse do not show it twice. Only runs of two-hex-digit
// groups are treated as bytes: a descriptor serial such as 4066-C535 is a name
// the kernel chose, not bytes, and stays as it is so unrelated devices cannot
// collapse into each other.
function canonicalSerial(serial) {
    if (typeof serial !== "string" || serial.length === 0)
        return ""
    const groups = serial.split(/[:-]/)
    if (groups.length >= 3 && groups.length <= 6 && groups.every(g => /^[0-9a-f]{2}$/i.test(g)))
        return groups.join("").toUpperCase()
    return serial.toUpperCase()
}

// One identity per device, used both for merging providers and for the hidden
// list, so hiding survives a device changing spelling or provider: hide the
// mouse while UPower reports f9-0d-4f-0c and it stays hidden when Solaar is the
// only source left and reports F90D4F0C. The object path covers devices with
// no serial at all, which otherwise all share the empty string.
function deviceIdentity(device) {
    if (!device)
        return ""
    return canonicalSerial(device.serial) || device.objectPath || ""
}

function getIconForType(deviceType) {
    switch (deviceType) {
        case "gaming-input":
        case "gamepad":
            return "input-gamepad"
        case "mouse":
            return "input-mouse"
        case "touchpad":
            return "input-touchpad"
        case "keyboard":
            return "input-keyboard"
        case "phone":
        case "smartphone":
            return "smartphone"
        case "tablet":
            return "tablet"
        case "headphones":
        case "audio-headphones":
            return "audio-headphones"
        case "headset":
        case "audio-headset":
            return "audio-headset"
        case "monitor":
        case "display":
            return "video-display"
        case "desktop":
            return "computer"
        case "laptop":
            return "computer-laptop"
        case "tv":
            return "video-television"
        default:
            return "battery-symbolic"
    }
}

// One entry per device reported by two providers: the earlier entry stays,
// the later one replaces a blocked placeholder or fills missing fields.
function mergeDuplicate(winner, later) {
    if (winner.blocked === true)
        return later.percentage != null ? later : winner;
    
    // A placeholder never replaces data; a multi-battery entry's readings
    // live in batteries, so percentage and charging have nothing to fill
    if (later.blocked === true || (winner.batteries && winner.batteries.length > 0))
        return winner;

    if (winner.percentage == null && later.percentage != null)
        winner = Object.assign({}, winner, {
            percentage: later.percentage
        });

    if (winner.charging == null && later.charging != null)
        winner = Object.assign({}, winner, {
            charging: later.charging
        });

    return winner;
}

// Merge devices from multiple providers, avoiding duplicates
// deviceProviders: array of device arrays in priority order (first = highest priority)
function mergeDevices(deviceProviders) {
    var merged = [];
    var seenIds = {};

    for (var providerIdx = 0; providerIdx < deviceProviders.length; providerIdx++) {
        var devices = deviceProviders[providerIdx];

        for (var i = 0; i < devices.length; i++) {
            var device = devices[i];
            var id = deviceIdentity(device);
            if (!id)
                continue;

            if (seenIds[id] === undefined) {
                merged.push(device);
                seenIds[id] = merged.length - 1;
            } else {
                merged[seenIds[id]] = mergeDuplicate(merged[seenIds[id]], device);
            }
        }
    }

    // Sort by name
    merged.sort((a, b) => {
        var nameA = a.name || "";
        var nameB = b.name || "";
        return nameA.localeCompare(nameB);
    });

    return merged;
}
