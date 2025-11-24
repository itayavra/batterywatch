import QtQuick 2.15

// Device information parser for UPower output
QtObject {
    id: parser
    
    required property var connectionTypes
    
    function parseDeviceInfo(output) {
        var lines = output.split("\n")
        var device = {
            name: "",
            serial: "",
            nativePath: "",
            percentage: -1,
            type: "",
            icon: "battery-symbolic",
            connectionType: connectionTypes.wired
        }
        
        var deviceType = ""
        
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i]
            var trimmedLine = line.trim()
            
            // Extract key-value pairs (these have colons)
            if (trimmedLine.indexOf("native-path:") !== -1) {
                device.nativePath = trimmedLine.split(":").slice(1).join(":").trim()
            }
            else if (trimmedLine.indexOf("serial:") !== -1) {
                device.serial = trimmedLine.split(":").slice(1).join(":").trim()
            }
            else if (trimmedLine.indexOf("model:") !== -1) {
                device.name = trimmedLine.split(":").slice(1).join(":").trim()
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
        
        // Determine connection type from native-path
        if (device.nativePath) {
            var path = device.nativePath.toLowerCase()
            var hasMacAddress = /[0-9a-f]{2}[:\-_][0-9a-f]{2}[:\-_][0-9a-f]{2}/.test(path)
            
            if (path.indexOf("bluez") !== -1 || 
                path.indexOf("bluetooth") !== -1 ||
                hasMacAddress) {
                device.connectionType = connectionTypes.bluetooth
            } else {
                device.connectionType = connectionTypes.wireless
            }
        }

        if (deviceType === "gaming-input") {
            device.type = "gamepad"
            device.icon = "input-gamepad"
        } else if (deviceType === "mouse") {
            device.type = "mouse"
            device.icon = "input-mouse"
        } else if (deviceType === "touchpad") {
            device.type = "touchpad"
            device.icon = "input-touchpad"
        } else if (deviceType === "keyboard") {
            device.type = "keyboard"
            device.icon = "input-keyboard"
        } else if (deviceType === "phone") {
            device.type = "phone"
            device.icon = "smartphone"
        } else if (deviceType === "tablet") {
            device.type = "tablet"
            device.icon = "tablet"
        } else if (deviceType === "headphones") {
            device.type = "headphones"
            device.icon = "audio-headphones"
        } else if (deviceType.length > 0) {
            device.type = deviceType
            device.icon = "battery-symbolic"
        }
        
        // Use native path as identifier if no serial/MAC 
        if (!device.serial && device.nativePath) {
            device.serial = device.nativePath
        }
        
        device.name = device.name
        
        return device
    }
}
