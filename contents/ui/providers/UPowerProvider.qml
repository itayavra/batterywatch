import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import "../DeviceUtils.js" as DeviceUtils

// UPower device provider
Item {
    id: root
    visible: false
    
    property var devices: []
    
    readonly property int wiredType: 0
    readonly property int wirelessType: 1
    readonly property int bluetoothType: 2
    
    // UPower device type overrides for devices incorrectly reported by UPower
    readonly property var upowerDeviceTypeOverrides: ({
        "logitech k400 plus": "keyboard",  // Keyboard with touchpad, reported as mouse
    })
    
    function refresh() {
        listSource.connectSource("upower -e")
    }
    
    // Parse UPower text output into device object
    function parseUPowerOutput(output, objectPath) {
        var lines = output.split("\n")
        var device = {
            name: "",
            serial: "",
            nativePath: "",
            percentage: -1,
            type: "",
            icon: "battery-symbolic",
            connectionType: root.wiredType,
            objectPath: objectPath,
            bluetoothAddress: "",
            source: "upower",
            batteries: [],
            model: ""
        }

        var deviceType = ""

        for (var i = 0; i < lines.length; i++) {
            var line = lines[i]
            var trimmedLine = line.trim()

            if (trimmedLine.indexOf("native-path:") !== -1) {
                device.nativePath = trimmedLine.split(":").slice(1).join(":").trim()
            }
            else if (trimmedLine.indexOf("serial:") !== -1) {
                device.serial = trimmedLine.split(":").slice(1).join(":").trim()
            }
            else if (trimmedLine.indexOf("model:") !== -1) {
                device.model = trimmedLine.split(":").slice(1).join(":").trim()
                device.name = device.model
            }
            else if (trimmedLine.indexOf("percentage:") !== -1) {
                var percentStr = trimmedLine.split(":")[1].trim().replace("%", "")
                device.percentage = parseInt(percentStr)
            }
            // Detect device type: exactly 2 spaces of indentation, single word, no colon
            else if (line.startsWith("  ") && !line.startsWith("    ") &&
                trimmedLine.indexOf(":") === -1 && trimmedLine.indexOf(" ") === -1 &&
                trimmedLine.length > 0) {
                deviceType = trimmedLine
            }
        }

        // Determine connection type from native-path and extract Bluetooth MAC address
        if (device.nativePath) {
            var path = device.nativePath.toLowerCase()
            var macMatch = path.match(/([0-9a-f]{2}[:\-_][0-9a-f]{2}[:\-_][0-9a-f]{2}[:\-_][0-9a-f]{2}[:\-_][0-9a-f]{2}[:\-_][0-9a-f]{2})/i)

            if (path.indexOf("bluez") !== -1 ||
                path.indexOf("bluetooth") !== -1 ||
                macMatch) {
                device.connectionType = root.bluetoothType
                // Extract and normalize MAC address for bluetoothctl
                if (macMatch) {
                    device.bluetoothAddress = macMatch[1].replace(/[_\-]/g, ":").toUpperCase()
                }
            } else {
                device.connectionType = root.wirelessType
            }
        }

        if (deviceType.length > 0) {
            device.type = deviceType
        }

        // Apply UPower-specific device type overrides for incorrectly reported devices
        if (device.model) {
            var modelLower = device.model.toLowerCase()
            var overrideType = root.upowerDeviceTypeOverrides[modelLower]
            if (overrideType) {
                console.log("BatteryWatch: Applying UPower device override for '" + device.model + "': " + 
                           device.type + " -> " + overrideType)
                device.type = overrideType
            }
        }

        if (device.type) {
            device.icon = DeviceUtils.getIconForType(device.type)
        }

        if (!device.serial && device.nativePath) {
            device.serial = device.nativePath
        }

        return device
    }
    
    P5Support.DataSource {
        id: listSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: (sourceName, data) => {
            disconnectSource(sourceName)
            
            var lines = data["stdout"].split("\n")
            var foundPaths = []
            
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim()
                if (line.startsWith("/org/freedesktop/UPower/devices/") && 
                    line.indexOf("DisplayDevice") === -1) {
                    foundPaths.push(line)
                    
                    // Fetch details for unknown devices
                    var known = root.devices.some(d => d.objectPath === line)
                    if (!known) {
                        detailsSource.connectSource("upower -i " + line)
                    }
                }
            }
            
            // Remove disconnected devices
            var filtered = root.devices.filter(d => !d.objectPath || foundPaths.indexOf(d.objectPath) !== -1)
            if (filtered.length !== root.devices.length) {
                root.devices = filtered
            }
        }
        
        Component.onCompleted: connectSource("upower -e")
    }
    
    P5Support.DataSource {
        id: detailsSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: (sourceName, data) => {
            disconnectSource(sourceName)
            
            var objectPath = sourceName.split(" ").pop()
            var info = parseUPowerOutput(data["stdout"], objectPath)
            
            if (info && info.connectionType !== root.wiredType && info.percentage >= 0) {
                // Update or add device
                var updated = false
                var newDevices = root.devices.map(d => {
                    if (d.objectPath === objectPath || (d.serial && d.serial === info.serial)) {
                        updated = true
                        return info
                    }
                    return d
                })
                
                if (!updated) {
                    newDevices.push(info)
                }
                
                newDevices.sort((a, b) => (a.name || "").localeCompare(b.name || ""))
                root.devices = newDevices
            }
        }
    }
    
    Timer {
        interval: 2000
        running: true
        repeat: true
        onTriggered: listSource.connectSource("upower -e")
    }
    
    Timer {
        interval: 60000
        running: true
        repeat: true
        onTriggered: {
            root.devices.forEach(d => {
                if (d.objectPath) {
                    detailsSource.connectSource("upower -i " + d.objectPath)
                }
            })
        }
    }
}
