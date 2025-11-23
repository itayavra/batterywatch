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
            
            if (deviceInfo && deviceInfo.isWireless && deviceInfo.percentage >= 0) {
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
            nativePath: "",
            percentage: -1,
            type: "",
            icon: "input-mouse",
            isWireless: false
        }
        
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim()
            
            // Check for wireless devices (Bluetooth, Xbox Wireless, etc.)
            if (line.indexOf("native-path:") !== -1) {
                device.nativePath = line.split(":")[1].trim()
                var path = line.toLowerCase()
                // Include bluez (Bluetooth), gip (Xbox wireless), and other wireless protocols
                if (path.indexOf("bluez") !== -1 || 
                    path.indexOf("bluetooth") !== -1 ||
                    path.indexOf("ps-controller") !== -1 ||
                    path.indexOf("hid") !== -1 ||
                    path.indexOf("gip") !== -1 || // Xbox Wireless dongle
                    /[0-9a-f]{2}[:\-_][0-9a-f]{2}[:\-_][0-9a-f]{2}/.test(path)) {
                    device.isWireless = true
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
        
        // Use native path as identifier if no serial/MAC (for Xbox wireless controllers)
        if (!device.serial && device.nativePath) {
            device.serial = device.nativePath
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
        Layout.minimumHeight: Kirigami.Units.gridUnit * 6
        Layout.preferredWidth: Kirigami.Units.gridUnit * 30
        // Dynamic height: header (gridUnit * 2.5) + device rows (gridUnit * 4 each)
        // Maximum of 3.5 rows = gridUnit * 14 for rows
        Layout.preferredHeight: {
            var headerHeight = Kirigami.Units.gridUnit * 2.5
            var rowHeight = Kirigami.Units.gridUnit * 4
            var deviceCount = bluetoothDevices.length
            var maxRows = 3.5
            var actualRows = Math.min(deviceCount, maxRows)
            return headerHeight + (actualRows * rowHeight) + Kirigami.Units.largeSpacing * 2
        }
        Layout.maximumHeight: Kirigami.Units.gridUnit * 2.5 + Kirigami.Units.gridUnit * 14 + Kirigami.Units.largeSpacing * 2
        
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing
            
            // Header with title and refresh button
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                
                PlasmaComponents.Label {
                    text: "Bluetooth Device Batteries"
                    font.bold: true
                    font.pixelSize: Kirigami.Theme.defaultFont.pixelSize * 1.2
                    Layout.fillWidth: true
                }
                
                PlasmaComponents.ToolButton {
                    icon.name: "view-refresh"
                    text: "Refresh"
                    display: PlasmaComponents.AbstractButton.IconOnly
                    
                    PlasmaComponents.ToolTip {
                        text: "Refresh devices"
                    }
                    
                    onClicked: {
                        deviceCheckCount = 0
                        deviceDetailsSource.pendingDevices = []
                        deviceDetailsSource.processedCount = 0
                        upowerSource.connectSource("upower -e")
                    }
                }
            }
            
            // Scrollable device list with fixed row heights
            PlasmaComponents.ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                
                contentWidth: availableWidth
                
                ColumnLayout {
                    width: parent.width
                    spacing: 0
                    
                    Repeater {
                        model: bluetoothDevices
                        
                        Item {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Kirigami.Units.gridUnit * 4
                            
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0
                                
                                Item {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Layout.topMargin: Kirigami.Units.smallSpacing
                                    Layout.bottomMargin: Kirigami.Units.smallSpacing
                                    
                                    RowLayout {
                                        anchors.fill: parent
                                        spacing: Kirigami.Units.smallSpacing
                                        
                                        Kirigami.Icon {
                                            source: modelData.icon
                                            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                            Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                                            Layout.alignment: Qt.AlignVCenter
                                        }
                                        
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            Layout.alignment: Qt.AlignVCenter
                                            spacing: 2
                                            
                                            PlasmaComponents.Label {
                                                text: modelData.name || "Unknown Device"
                                                font.bold: true
                                                Layout.fillWidth: true
                                                elide: Text.ElideRight
                                            }
                                            
                                            PlasmaComponents.Label {
                                                text: modelData.serial
                                                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                                                color: Kirigami.Theme.disabledTextColor
                                                Layout.fillWidth: true
                                                elide: Text.ElideRight
                                            }
                                        }
                                        
                                        RowLayout {
                                            Layout.alignment: Qt.AlignVCenter
                                            spacing: Kirigami.Units.smallSpacing
                                            
                                            PlasmaComponents.ToolButton {
                                                icon.name: hiddenDevices.indexOf(modelData.serial) === -1 ? "view-visible" : "view-hidden"
                                                text: hiddenDevices.indexOf(modelData.serial) === -1 ? "Hide" : "Show"
                                                display: PlasmaComponents.AbstractButton.IconOnly
                                                onClicked: toggleDeviceVisibility(modelData.serial)
                                                
                                                PlasmaComponents.ToolTip {
                                                    text: hiddenDevices.indexOf(modelData.serial) === -1 ? "Hide from tray" : "Show in tray"
                                                }
                                                
                                                MouseArea {
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    cursorShape: Qt.PointingHandCursor
                                                    onPressed: mouse.accepted = false
                                                }
                                            }
                                            
                                            PlasmaComponents.ToolButton {
                                                icon.name: "network-disconnect"
                                                text: "Disconnect"
                                                display: PlasmaComponents.AbstractButton.IconOnly
                                                onClicked: disconnectDevice(modelData.serial)
                                                
                                                PlasmaComponents.ToolTip {
                                                    text: "Disconnect device"
                                                }
                                                
                                                MouseArea {
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    cursorShape: Qt.PointingHandCursor
                                                    onPressed: mouse.accepted = false
                                                }
                                            }
                                            
                                            PlasmaComponents.Label {
                                                text: modelData.percentage + "%"
                                                font.bold: true
                                                Layout.minimumWidth: Kirigami.Units.gridUnit * 3
                                                horizontalAlignment: Text.AlignRight
                                            }
                                        }
                                    }
                                }
                                
                                Kirigami.Separator {
                                    Layout.fillWidth: true
                                    visible: index < bluetoothDevices.length - 1
                                }
                            }
                        }
                    }
                    
                    PlasmaComponents.Label {
                        visible: bluetoothDevices.length === 0
                        text: "No Bluetooth devices with battery info found"
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.largeSpacing
                        horizontalAlignment: Text.AlignHCenter
                        color: Kirigami.Theme.disabledTextColor
                    }
                }
            }
        }
    }
}