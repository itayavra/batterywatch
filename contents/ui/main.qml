import QtQuick 2.15
import QtQuick.Layouts
import org.kde.plasma.plasmoid 2.0
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.components 3.0 as PlasmaComponents
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami 2.20 as Kirigami
import org.kde.config as KConfig

PlasmoidItem {
    id: root
    
    property var bluetoothDevices: []
    property var hiddenDevices: [] // List of MAC addresses to hide
    
    // Prefer compact representation (icon in tray)
    preferredRepresentation: compactRepresentation
    
    // Tooltip properties
    toolTipMainText: "Bluetooth Battery Monitor"
    toolTipSubText: "No devices"
    
    // Hide widget when no visible devices
    Plasmoid.status: {
        var visibleCount = 0
        for (var i = 0; i < bluetoothDevices.length; i++) {
            if (hiddenDevices.indexOf(bluetoothDevices[i].serial) === -1) {
                visibleCount++
            }
        }
        return visibleCount > 0 ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.HiddenStatus
    }
    
    function updateTooltip() {
        if (bluetoothDevices.length === 0) {
            toolTipSubText = "No Bluetooth devices"
        } else {
            var lines = []
            for (var i = 0; i < bluetoothDevices.length; i++) {
                var device = bluetoothDevices[i]
                if (hiddenDevices.indexOf(device.serial) === -1) {
                    var displayName = device.name
                    if (device.serial) {
                        displayName += "\n" + device.serial
                    }
                    lines.push(displayName + ": " + device.percentage + "%")
                }
            }
            toolTipSubText = lines.length > 0 ? lines.join("\n\n") : "All devices hidden"
        }
    }
    
    function loadHiddenDevices() {
        var saved = Plasmoid.configuration.hiddenDevices
        if (saved) {
            hiddenDevices = saved.split(",").filter(function(s) { return s.length > 0 })
        } else {
            hiddenDevices = []
        }
    }
    
    function saveHiddenDevices() {
        Plasmoid.configuration.hiddenDevices = hiddenDevices.join(",")
    }
    
    function toggleDeviceVisibility(serial) {
        var index = hiddenDevices.indexOf(serial)
        if (index === -1) {
            hiddenDevices.push(serial)
        } else {
            hiddenDevices.splice(index, 1)
        }
        hiddenDevices = hiddenDevices.slice() // Trigger property change
        saveHiddenDevices()
        updateTooltip()
        Plasmoid.status = Plasmoid.status // Force status update
    }
    
    function disconnectDevice(serial) {
        // Disconnect via bluetoothctl
        bluetoothCtlSource.connectSource("bluetoothctl disconnect " + serial)
    }
    
    Component.onCompleted: {
        loadHiddenDevices()
    }
    
    // D-Bus connection to UPower
    P5Support.DataSource {
        id: upowerSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName)
            
            var lines = data["stdout"].split("\n")
            deviceCheckCount = 0
            deviceDetailsSource.pendingDevices = []
            deviceDetailsSource.processedCount = 0
            
            // Count how many devices we need to check
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim()
                if (line.startsWith("/org/freedesktop/UPower/devices/") && 
                    line.indexOf("DisplayDevice") === -1) {
                    deviceCheckCount++
                }
            }
            
            // If no devices, clear the list immediately
            if (deviceCheckCount === 0) {
                bluetoothDevices = []
                updateTooltip()
                return
            }
            
            // Now query each device
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim()
                if (line.startsWith("/org/freedesktop/UPower/devices/") && 
                    line.indexOf("DisplayDevice") === -1) {
                    getDeviceDetails(line)
                }
            }
        }
        
        Component.onCompleted: {
            connectSource("upower -e")
        }
    }
    
    P5Support.DataSource {
        id: deviceDetailsSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        property var pendingDevices: []
        property int processedCount: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName)
            
            var output = data["stdout"]
            var deviceInfo = parseDeviceInfo(output)
            
            if (deviceInfo && deviceInfo.isBluetooth && deviceInfo.percentage >= 0) {
                pendingDevices.push(deviceInfo)
            }
            
            processedCount++
            
            // Check if all devices have been processed
            if (processedCount >= deviceCheckCount) {
                // Sort by name first, then by serial/MAC address
                pendingDevices.sort(function(a, b) {
                    var nameCompare = a.name.localeCompare(b.name)
                    if (nameCompare !== 0) {
                        return nameCompare
                    }
                    return a.serial.localeCompare(b.serial)
                })
                bluetoothDevices = pendingDevices.slice()
                updateTooltip()
                pendingDevices = []
                processedCount = 0
                deviceCheckCount = 0
            }
        }
    }
    
    P5Support.DataSource {
        id: bluetoothCtlSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName)
            // Trigger refresh after disconnect
            Qt.callLater(function() {
                deviceCheckCount = 0
                deviceDetailsSource.pendingDevices = []
                deviceDetailsSource.processedCount = 0
                upowerSource.connectSource("upower -e")
            })
        }
    }
    
    property int deviceCheckCount: 0
    
    function getDeviceDetails(devicePath) {
        deviceDetailsSource.connectSource("upower -i " + devicePath)
    }
    
    function parseDeviceInfo(output) {
        var lines = output.split("\n")
        var device = {
            name: "",
            serial: "",
            percentage: -1,
            type: "",
            icon: "input-mouse",
            isBluetooth: false
        }
        
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim()
            
            // Check for Bluetooth devices
            if (line.indexOf("native-path:") !== -1) {
                var path = line.toLowerCase()
                if (path.indexOf("bluez") !== -1 || 
                    path.indexOf("bluetooth") !== -1 ||
                    path.indexOf("ps-controller") !== -1 ||
                    path.indexOf("hid") !== -1 ||
                    /[0-9a-f]{2}[:\-_][0-9a-f]{2}[:\-_][0-9a-f]{2}/.test(path)) {
                    device.isBluetooth = true
                }
            }
            
            // Get device serial/MAC address
            if (line.indexOf("serial:") !== -1) {
                device.serial = line.split(":").slice(1).join(":").trim()
            }
            
            // Get device model/name
            if (line.indexOf("model:") !== -1) {
                device.name = line.split(":")[1].trim()
            }
            
            // Get battery percentage
            if (line.indexOf("percentage:") !== -1) {
                var percentStr = line.split(":")[1].trim().replace("%", "")
                device.percentage = parseInt(percentStr)
            }
            
            // Determine device type and icon
            var lowerLine = line.toLowerCase()
            if (lowerLine.indexOf("gaming-input") !== -1 || 
                lowerLine.indexOf("gaming") !== -1 || 
                lowerLine.indexOf("controller") !== -1 || 
                lowerLine.indexOf("gamepad") !== -1 ||
                lowerLine.indexOf("dualsense") !== -1 ||
                lowerLine.indexOf("dualshock") !== -1 ||
                lowerLine.indexOf("xbox") !== -1) {
                device.type = "gamepad"
                device.icon = "input-gamepad"
            } else if (lowerLine.indexOf("mouse") !== -1) {
                device.type = "mouse"
                device.icon = "input-mouse"
            } else if (lowerLine.indexOf("keyboard") !== -1) {
                device.type = "keyboard"
                device.icon = "input-keyboard"
            } else if (lowerLine.indexOf("headset") !== -1 || 
                       lowerLine.indexOf("headphone") !== -1 ||
                       lowerLine.indexOf("earbuds") !== -1) {
                device.type = "headset"
                device.icon = "audio-headset"
            } else if (lowerLine.indexOf("phone") !== -1 ||
                       lowerLine.indexOf("mobile") !== -1) {
                device.type = "phone"
                device.icon = "smartphone"
            } else if (lowerLine.indexOf("tablet") !== -1) {
                device.type = "tablet"
                device.icon = "tablet"
            }
        }
        
        return device
    }
    
    // Timer to refresh device list periodically
    Timer {
        id: refreshTimer
        interval: 5000 // 5 seconds
        running: true
        repeat: true
        
        onTriggered: {
            deviceCheckCount = 0
            deviceDetailsSource.pendingDevices = []
            deviceDetailsSource.processedCount = 0
            upowerSource.connectSource("upower -e")
        }
    }
    
    // Compact representation (what shows in the system tray)
    compactRepresentation: Item {
        Layout.preferredWidth: row.implicitWidth
        Layout.preferredHeight: row.implicitHeight
        
        RowLayout {
            id: row
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing
            
            Repeater {
                model: bluetoothDevices
                
                RowLayout {
                    visible: hiddenDevices.indexOf(modelData.serial) === -1
                    spacing: 2
                    
                    Kirigami.Icon {
                        source: modelData.icon
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                    }
                    
                    PlasmaComponents.Label {
                        text: modelData.percentage + "%"
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }
                }
            }
        }
        
        MouseArea {
            anchors.fill: parent
            onClicked: root.expanded = !root.expanded
        }
    }
    
    // Full representation (popup when clicked)
    fullRepresentation: Item {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 25
        Layout.minimumHeight: Kirigami.Units.gridUnit * 10
        Layout.preferredWidth: Kirigami.Units.gridUnit * 30
        Layout.preferredHeight: column.implicitHeight + Kirigami.Units.gridUnit * 2
        
        ColumnLayout {
            id: column
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing
            
            PlasmaComponents.Label {
                text: "Bluetooth Device Batteries"
                font.bold: true
                font.pixelSize: Kirigami.Theme.defaultFont.pixelSize * 1.2
            }
            
            Repeater {
                model: bluetoothDevices
                
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    
                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: deviceRow.implicitHeight
                        
                        property bool isHovered: false
                        
                        FlexboxLayout {
                            id: deviceRow
                            anchors.fill: parent
                            gap: Kirigami.Units.smallSpacing
                            justifyContent: FlexboxLayout.JustifySpaceBetween
                            alignContent: FlexboxLayout.AlignCenter
                            alignItems: FlexboxLayout.AlignCenter
                            
                            Kirigami.Icon {
                                source: modelData.icon
                                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                            }
                            
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Kirigami.Units.smallSpacing
                                
                                PlasmaComponents.Label {
                                    text: modelData.name || "Unknown Device"
                                    font.bold: true
                                }
                                
                                PlasmaComponents.Label {
                                    text: modelData.serial
                                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                                    color: Kirigami.Theme.disabledTextColor
                                }
                            }
                            
                            Item {
                                Layout.fillWidth: true
                            }
                            
                            FlexboxLayout {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                justifyContent: FlexboxLayout.JustifyEnd
                                alignItems: FlexboxLayout.AlignCenter
                                gap: 15

                                PlasmaComponents.ProgressBar {
                                    Layout.preferredWidth: Kirigami.Units.gridUnit * 6
                                    visible: !parent.parent.parent.isHovered
                                    from: 0
                                    to: 100
                                    value: modelData.percentage
                                }
                                
                                RowLayout {
                                    visible: parent.parent.parent.isHovered
                                    
                                    PlasmaComponents.ToolButton {
                                        icon.name: hiddenDevices.indexOf(modelData.serial) === -1 ? "view-visible" : "view-hidden"
                                        text: hiddenDevices.indexOf(modelData.serial) === -1 ? "Hide" : "Show"
                                        display: PlasmaComponents.AbstractButton.IconOnly
                                        onClicked: toggleDeviceVisibility(modelData.serial)
                                    }
                                    
                                    PlasmaComponents.ToolButton {
                                        icon.name: "network-disconnect"
                                        text: "Disconnect"
                                        display: PlasmaComponents.AbstractButton.IconOnly
                                        onClicked: disconnectDevice(modelData.serial)
                                    }
                                }
                                
                                PlasmaComponents.Label {
                                    text: modelData.percentage + "%"
                                    font.bold: true
                                }
                            }
                        }
                        
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            
                            onEntered: parent.isHovered = true
                            onExited: parent.isHovered = false
                            
                            // Pass clicks through to buttons
                            onPressed: mouse.accepted = false
                        }
                    }
                    
                    Kirigami.Separator {
                        Layout.fillWidth: true
                        visible: index < bluetoothDevices.length - 1
                    }
                }
            }
            
            PlasmaComponents.Label {
                visible: bluetoothDevices.length === 0
                text: "No Bluetooth devices with battery info found"
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                color: Kirigami.Theme.disabledTextColor
            }
            
            Item {
                Layout.fillHeight: true
            }
            
            PlasmaComponents.Button {
                text: "Refresh"
                icon.name: "view-refresh"
                Layout.alignment: Qt.AlignHCenter
                
                onClicked: {
                    deviceCheckCount = 0
                    deviceDetailsSource.pendingDevices = []
                    deviceDetailsSource.processedCount = 0
                    upowerSource.connectSource("upower -e")
                }
            }
        }
    }
}