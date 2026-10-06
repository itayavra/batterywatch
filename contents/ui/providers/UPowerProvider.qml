import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils

// UPower device provider
Item {
    id: root
    visible: false
    
    property bool upowerEnabled: Plasmoid.configuration.enableUPowerIntegration
    property var devices: []
    
    readonly property int wiredType: 0
    readonly property int wirelessType: 1
    readonly property int bluetoothType: 2
    
    // UPower device type overrides for devices incorrectly reported by UPower
    readonly property var upowerDeviceTypeOverrides: ({
        "logitech k400 plus": "keyboard",  // Keyboard with touchpad, reported as mouse
        // Wireless mice, reported as keyboards when connected via USB cable
        "pro x wireless": "mouse",
        "logitech g903 wired/wireless gaming mouse": "mouse",
        // PowerPlay / Lightspeed: HID++ advertises G-keys as a keyboard collection
        "g502 lightspeed wireless gaming mouse": "mouse",
    })
    
    function refresh() {
        if (!root.upowerEnabled)
            return
        listSource.connectSource("upower -e")
        root.devices.forEach(d => {
            if (d.objectPath) {
                detailsSource.disconnectSource("upower -i " + d.objectPath)
                detailsSource.connectSource("upower -i " + d.objectPath)
            }
        })
    }

    onUpowerEnabledChanged: {
        if (root.upowerEnabled) {
            root.refresh()
            return
        }
        listSource.disconnectSource("upower -e")
        root.devices.forEach(d => {
            if (d.objectPath)
                detailsSource.disconnectSource("upower -i " + d.objectPath)
        })
        root.devices = []
    }
    
    // Parse UPower text output into device object
    function parseUPowerOutput(output, objectPath) {
        var lines = output.split("\n")
        var device = {
            name: "",
            serial: "",
            nativePath: "",
            percentage: -1,
            charging: false,
            type: "",
            icon: "battery-symbolic",
            connectionType: root.wiredType,
            objectPath: objectPath,
            bluetoothAddress: "",
            source: "upower",
            batteries: [],
            model: "",
            batteryLevel: "",
            percentageIgnored: false
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
                var percentStr = trimmedLine.split(":")[1].trim()
                // UPower appends "(should be ignored)" when it is serving a
                // reading it does not trust - a stale or absent battery.
                // Strip it before parsing, and remember that it was there.
                device.percentageIgnored = percentStr.indexOf("should be ignored") !== -1
                device.percentage = parseInt(percentStr.replace("%", "").replace("(should be ignored)", ""))
            }
            else if (trimmedLine.indexOf("battery-level:") !== -1) {
                // A HID++ battery node stays registered as long as the *receiver*
                // is powered, so a mouse that is switched off keeps appearing in
                // `upower -e`. UPower then reports battery-level "unknown" with
                // "0% (should be ignored)" - a parse of which yields 0 and passes
                // the percentage gate below, pinning the device in the list at 0%.
                // battery-level is the signal that distinguishes that stale node
                // from a real battery that is genuinely empty ("empty").
                device.batteryLevel = trimmedLine.split(":")[1].trim()
            }
            else if (trimmedLine.indexOf("state:") !== -1) {
                device.charging = trimmedLine.split(":")[1].trim() === "charging"
            }
            else if (trimmedLine.indexOf("icon-name:") !== -1) {
                if (trimmedLine.indexOf("charging") !== -1)
                    device.charging = true
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
            } else if (path.indexOf("hidpp") !== -1 && device.serial) {
                // hidpp batteries put their transport in the serial: a fully
                // colon-separated MAC means Bluetooth. Other transports (USB
                // receiver, cable) report a dash-separated uniq or a raw
                // HID++ serial - never a colon MAC - so nothing false-matches
                var serialMac = device.serial.match(/^([0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2})$/i)
                if (serialMac) {
                    device.connectionType = root.bluetoothType
                    device.bluetoothAddress = serialMac[1].replace(/[_\-]/g, ":").toUpperCase()
                } else {
                    device.connectionType = root.wirelessType
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
				// i18n: Used when a device is known by BatteryWatch to be misreported by UPower. 
				// %1 is the device's model name. %2 is the erroneously reported device type (e.g.: ‘mouse’). 
				// %3 is the correct device type.
                console.log(i18n("BatteryWatch: Applying UPower device override for '%1': %2 -> %3", 
                    device.model, device.type, overrideType))
                device.type = overrideType
            }
        }

        if (device.type) {
            device.icon = DeviceUtils.getIconForType(device.type)
        }

        if (!device.serial && device.nativePath) {
            device.serial = device.nativePath
        }

        if (device.connectionType === root.bluetoothType && device.bluetoothAddress) {
            const addr = device.bluetoothAddress
            device.disconnect = () => btDisconnectSource.connectSource("bluetoothctl disconnect " + addr)
            device.disconnectTooltip = i18n("Disconnect device")
        }

        return device
    }

    P5Support.DataSource {
        id: btDisconnectSource
        engine: "executable"
        interval: 0
        // UPower list refreshes every 2s automatically; no explicit post-action needed
        onNewData: (src, data) => disconnectSource(src)
    }

    P5Support.DataSource {
        id: listSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: (sourceName, data) => {
            disconnectSource(sourceName)
            if (!root.upowerEnabled) {
                root.devices = []
                return
            }
            
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
            
            // Remove disconnected devices and their detail sources
            var filtered = root.devices.filter(d => !d.objectPath || foundPaths.indexOf(d.objectPath) !== -1)
            if (filtered.length !== root.devices.length) {
                root.devices.forEach(d => {
                    if (d.objectPath && foundPaths.indexOf(d.objectPath) === -1)
                        detailsSource.disconnectSource("upower -i " + d.objectPath)
                })
                root.devices = filtered
            }
        }
        
        Component.onCompleted: if (root.upowerEnabled) connectSource("upower -e")
    }
    
    P5Support.DataSource {
        id: detailsSource
        engine: "executable"
        connectedSources: []
        interval: 10000

        onNewData: (sourceName, data) => {
            if (!root.upowerEnabled) {
                root.devices = []
                return
            }
            var objectPath = sourceName.split(" ").pop()
            var info = parseUPowerOutput(data["stdout"], objectPath)

            // A receiver-backed HID++ battery stays enumerated while the device behind it
            // is off, so `upower -e` cannot drop it - only its detail reply can.
            // UPower then serves a stale reading flagged "(should be ignored)"
            // alongside battery-level "unknown". Requiring BOTH keeps this
            // conservative: a device with no usable battery reading has nothing
            // to show, while a genuinely empty battery reports "empty" and a
            // trusted percentage and is kept.
            if (info && info.batteryLevel === "unknown" && info.percentageIgnored) {
                var without = root.devices.filter(d => d.objectPath !== objectPath)
                if (without.length !== root.devices.length) {
                    root.devices = without.sort((a, b) => (a.name || "").localeCompare(b.name || ""))
                }
                return
            }

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
        running: root.upowerEnabled
        repeat: true
        onTriggered: listSource.connectSource("upower -e")
    }

}
