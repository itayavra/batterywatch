// UPower device parsing and management logic

.import "../DeviceParser.js" as DeviceParser

// Connection type constants
var ConnectionType = {
    wired: 0,
    wireless: 1,
    bluetooth: 2
}

// Parse upower -e output, return list of device paths to fetch
function parseDeviceList(output, knownDevices) {
    var lines = output.split("\n")
    var foundPaths = []
    var newPaths = []
    
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim()
        if (line.startsWith("/org/freedesktop/UPower/devices/") && 
            line.indexOf("DisplayDevice") === -1) {
            foundPaths.push(line)
            
            var known = false
            for (var j = 0; j < knownDevices.length; j++) {
                if (knownDevices[j].objectPath === line) {
                    known = true
                    break
                }
            }
            if (!known) {
                newPaths.push(line)
            }
        }
    }
    
    return {
        foundPaths: foundPaths,
        newPaths: newPaths
    }
}

// Remove devices that are no longer present
function filterDisconnectedDevices(devices, foundPaths) {
    return devices.filter(function(d) {
        return !d.objectPath || foundPaths.indexOf(d.objectPath) !== -1
    })
}

// Parse upower -i output for a specific device
function parseDeviceDetails(output, objectPath) {
    var deviceInfo = DeviceParser.parseDeviceInfo(output, ConnectionType)
    
    // Only include wireless/Bluetooth devices with valid battery
    if (deviceInfo && deviceInfo.connectionType !== ConnectionType.wired && deviceInfo.percentage >= 0) {
        deviceInfo.objectPath = objectPath
        deviceInfo.source = "upower"
        return deviceInfo
    }
    
    return null
}

// Update or add a device to the list
function updateDeviceInList(devices, deviceInfo) {
    var found = false
    var newDevices = devices.slice()
    
    for (var i = 0; i < newDevices.length; i++) {
        var sameSerial = newDevices[i].serial && newDevices[i].serial === deviceInfo.serial
        var samePath = newDevices[i].objectPath && newDevices[i].objectPath === deviceInfo.objectPath
        
        if (sameSerial || samePath) {
            newDevices[i] = deviceInfo
            found = true
            break
        }
    }
    
    if (!found) {
        newDevices.push(deviceInfo)
    }
    
    // Sort by name
    newDevices.sort(function(a, b) {
        return (a.name || "").localeCompare(b.name || "")
    })
    
    return newDevices
}

