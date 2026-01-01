// Companion service parsing logic

.import "../DeviceParser.js" as DeviceParser

// Parse gdbus call output
function parseGdbusOutput(output) {
    // gdbus returns: ('json_string',)
    var match = output.match(/\('(.*)'\,?\)/)
    if (!match || !match[1]) {
        return null
    }
    
    // Unescape the string (gdbus escapes special chars)
    var jsonStr = match[1]
        .replace(/\\'/g, "'")
        .replace(/\\"/g, '"')
        .replace(/\\\\/g, '\\')
    
    try {
        var data = JSON.parse(jsonStr)
        if (!Array.isArray(data)) {
            console.warn("BatteryWatch: Companion returned non-array")
            return null
        }
        return data
    } catch (e) {
        console.warn("BatteryWatch: Failed to parse companion JSON:", e)
        return null
    }
}

// Convert companion device format to widget device format
// Defensive: handles missing/unexpected fields gracefully
function parseCompanionDevice(data) {
    if (!data || typeof data !== 'object') {
        return null
    }
    
    // Required field
    var id = data.id || data.address || ""
    if (!id) {
        return null
    }
    
    // Get icon from device_type or use provided icon_name
    var deviceType = data.device_type || "unknown"
    var icon = data.icon_name || DeviceParser.getIconForType(deviceType)
    
    // Handle batteries array - calculate average percentage
    var batteries = []
    var percentage = 0
    
    if (Array.isArray(data.batteries) && data.batteries.length > 0) {
        var total = 0
        for (var i = 0; i < data.batteries.length; i++) {
            var bat = data.batteries[i]
            var pct = typeof bat.percentage === 'number' ? bat.percentage : 0
            total += pct
            batteries.push({
                label: bat.label || null,
                percentage: pct,
                charging: bat.charging === true
            })
        }
        percentage = Math.round(total / batteries.length)
    } else if (typeof data.percentage === 'number') {
        percentage = data.percentage
    }
    
    return {
        name: data.name || data.model || "Unknown Device",
        serial: id,
        percentage: percentage,
        icon: icon,
        type: deviceType,
        batteries: batteries,
        model: data.model || "",
        source: "companion",
        nativePath: "",
        objectPath: "",
        connectionType: 2, // bluetooth
        bluetoothAddress: id
    }
}

// Parse all companion devices from gdbus output
function parseAllDevices(output) {
    var rawDevices = parseGdbusOutput(output)
    if (!rawDevices) {
        return null
    }
    
    var devices = []
    for (var i = 0; i < rawDevices.length; i++) {
        var parsed = parseCompanionDevice(rawDevices[i])
        if (parsed) {
            devices.push(parsed)
        }
    }
    
    return devices
}

