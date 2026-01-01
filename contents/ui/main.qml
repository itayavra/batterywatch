import QtQuick 2.15
import QtQuick.Layouts
import org.kde.plasma.plasmoid 2.0
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.components 3.0 as PlasmaComponents
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami 2.20 as Kirigami
import "DeviceParser.js" as DeviceParser

PlasmoidItem {
    id: root
    
    property var connectedDevices: []
    property var hiddenDevices: []
    
    property int visibleDeviceCount: {
        var count = 0
        for (var i = 0; i < connectedDevices.length; i++) {
            if (hiddenDevices.indexOf(connectedDevices[i].serial) === -1) {
                count++
            }
        }
        return count
    }
    
    property bool hasVisibleDevices: visibleDeviceCount > 0
    property bool hasAnyDevices: connectedDevices.length > 0
    property bool allDevicesHidden: hasAnyDevices && !hasVisibleDevices
    

    
    preferredRepresentation: compactRepresentation
    
    toolTipMainText: "BatteryWatch"
    toolTipSubText: "No devices"
    
    // Hide widget when no visible devices (except when user is configuring or panel is in edit mode)
    Plasmoid.status: {
        if (Plasmoid.userConfiguring) {
            return PlasmaCore.Types.ActiveStatus
        }

        if (Plasmoid.containment && Plasmoid.containment.corona && Plasmoid.containment.corona.editMode) {
            return PlasmaCore.Types.ActiveStatus
        }

        // Show widget if there are ANY devices (even if all hidden), so users can unhide them
        return hasAnyDevices ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.HiddenStatus
    }

    QtObject {
        id: connectionType
        readonly property int wired: 0
        readonly property int wireless: 1
        readonly property int bluetooth: 2
    }

    
    function updateTooltip() {
        if (connectedDevices.length === 0) {
            toolTipSubText = "No connected devices"
        } else {
            var lines = []
            for (var i = 0; i < connectedDevices.length; i++) {
                var device = connectedDevices[i]
                if (hiddenDevices.indexOf(device.serial) === -1) {
                    var displayName = device.name
                    if (device.serial) {
                        displayName += "\n" + device.serial
                    }
                    lines.push(displayName + ": " + device.percentage + "%")
                }
            }
            toolTipSubText = lines.length > 0 ? lines.join("\n\n") : "All devices hidden\nClick to unhide"
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
    }
    
    function disconnectBluetoothDevice(bluetoothAddress) {
        if (bluetoothAddress) {
            bluetoothCtlSource.connectSource("bluetoothctl disconnect " + bluetoothAddress)
        }
    }
    
    function refreshDevices() {
        upowerPresenceSource.connectSource("upower -e")
    }
    
    Component.onCompleted: {
        loadHiddenDevices()
    }
    
    P5Support.DataSource {
        id: upowerPresenceSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName)
            var lines = data["stdout"].split("\n")
            var foundPaths = []
            
            // Collect all current valid device paths
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim()
                if (line.startsWith("/org/freedesktop/UPower/devices/") && 
                    line.indexOf("DisplayDevice") === -1) {
                    foundPaths.push(line)
                    
                    var known = false
                    for (var j = 0; j < connectedDevices.length; j++) {
                        // Compare against the DBus object path
                        if (connectedDevices[j].objectPath === line) {
                            known = true
                            break
                        }
                    }
                    if (!known) {
                        refreshSpecificDevice(line)
                    }
                }
            }
            
            // Remove devices that are no longer present
            var pathsToRemove = []
            for (var i = 0; i < connectedDevices.length; i++) {
                var device = connectedDevices[i]
                if (device.objectPath && foundPaths.indexOf(device.objectPath) === -1) {
                    pathsToRemove.push(device.objectPath)
                }
            }
            
            for (var i = 0; i < pathsToRemove.length; i++) {
                handleDeviceRemoved(pathsToRemove[i])
            }
        }
        
        Component.onCompleted: {
            connectSource("upower -e")
        }
    }
    
    // Presence Timer: Checks for connected devices
    Timer {
        id: presenceTimer
        interval: 2000 
        running: true
        repeat: true
        onTriggered: {
            upowerPresenceSource.connectSource("upower -e")
        }
    }
    
    // Battery Update Timer: Refreshes levels for connected devices
    Timer {
        id: updateTimer
        interval: 60000 
        running: true
        repeat: true
        onTriggered: {
            for (var i = 0; i < connectedDevices.length; i++) {
                if (connectedDevices[i].objectPath) {
                    refreshSpecificDevice(connectedDevices[i].objectPath)
                }
            }
        }
    }
    

    
    // 3. Device Details Fetcher: Gets info for specific device
    P5Support.DataSource {
        id: deviceDetailsSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName) // Single shot
            
            // Extract the original DBus path from the command
            // sourceName is "upower -i /org/freedesktop/UPower/devices/..."
            var parts = sourceName.split(" ")
            var objectPath = parts[parts.length-1]
            
            var output = data["stdout"]
            var deviceInfo = DeviceParser.parseDeviceInfo(output, connectionType)
            
            if (deviceInfo && deviceInfo.percentage >= 0) {
                // Store the DBus object path for syncing
                deviceInfo.objectPath = objectPath
                updateOrAddDevice(deviceInfo)
            }
        }
    }
    
    function refreshSpecificDevice(path) {
        deviceDetailsSource.connectSource("upower -i " + path)
    }
    
    P5Support.DataSource {
        id: bluetoothCtlSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName)
            // Trigger refresh after disconnect
            Qt.callLater(refreshDevices)
        }
    }
    

    
    function updateOrAddDevice(deviceInfo) {
        var found = false
        for (var i = 0; i < connectedDevices.length; i++) {
            var sameSerial = connectedDevices[i].serial && connectedDevices[i].serial === deviceInfo.serial
            var samePath = connectedDevices[i].objectPath && connectedDevices[i].objectPath === deviceInfo.objectPath
            
            if (sameSerial || samePath) {
                connectedDevices[i] = deviceInfo
                found = true
                break
            }
        }
        
        if (!found) {
            connectedDevices.push(deviceInfo)
        }
        
        // Re-sort and trigger update
        connectedDevices.sort(function(a, b) {
            var nameCompare = a.name.localeCompare(b.name)
            if (nameCompare !== 0) return nameCompare
            return a.serial.localeCompare(b.serial)
        })
        connectedDevices = connectedDevices.slice() // Trigger property change
        updateTooltip()
    }
    
    function handleDeviceRemoved(objectPath) {
        var newDevices = []
        for (var i = 0; i < connectedDevices.length; i++) {
            if (connectedDevices[i].objectPath !== objectPath) {
                newDevices.push(connectedDevices[i])
            }
        }
        connectedDevices = newDevices
        updateTooltip()
    }
    
    compactRepresentation: Item {
        property bool inEditMode: {
            if (Plasmoid.userConfiguring) return true
            if (Plasmoid.containment && Plasmoid.containment.corona && Plasmoid.containment.corona.editMode) return true
            return false
        }
        
        // Show if there are visible devices, all devices are hidden, or in edit mode
        property bool shouldShow: root.hasVisibleDevices || root.allDevicesHidden || inEditMode
        
        // Only take space when we should be visible
        Layout.minimumWidth: shouldShow ? -1 : 0
        Layout.minimumHeight: shouldShow ? -1 : 0
        Layout.preferredWidth: shouldShow ? (root.hasVisibleDevices ? row.implicitWidth : placeholderIcon.width) : 0
        Layout.preferredHeight: shouldShow ? (root.hasVisibleDevices ? row.implicitHeight : placeholderIcon.height) : 0
        Layout.maximumWidth: shouldShow ? -1 : 0
        Layout.maximumHeight: shouldShow ? -1 : 0
        
        Kirigami.Icon {
            id: placeholderIcon
            anchors.centerIn: parent
            source: root.allDevicesHidden ? Qt.resolvedUrl("../icons/hidden-devices.png") : Qt.resolvedUrl("../icons/battery-monitor.png")
            width: Kirigami.Units.iconSizes.smallMedium
            height: Kirigami.Units.iconSizes.smallMedium
            visible: !root.hasVisibleDevices && (inEditMode || root.allDevicesHidden)
        }
        
        RowLayout {
            id: row
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing
            visible: root.hasVisibleDevices
            
            Repeater {
                model: connectedDevices
                
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
    
    fullRepresentation: Item {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 25
        Layout.preferredWidth: Kirigami.Units.gridUnit * 30
        Layout.minimumHeight: Kirigami.Units.gridUnit * 8
        Layout.preferredHeight: {
            var baseHeight = Kirigami.Units.gridUnit * 5
            var deviceHeight = connectedDevices.length * Kirigami.Units.gridUnit * 4
            var totalHeight = baseHeight + deviceHeight
            var maxHeight = Kirigami.Units.gridUnit * 17
            return Math.min(totalHeight, maxHeight)
        }
        Layout.maximumHeight: Kirigami.Units.gridUnit * 17
        
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing
            
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                
                PlasmaComponents.Label {
                    text: "Device Battery Levels"
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
                        refreshDevices()
                    }
                }
            }
            
            PlasmaComponents.ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                
                clip: true
                
                PlasmaComponents.ScrollBar.horizontal.policy: PlasmaComponents.ScrollBar.AlwaysOff
                
                ColumnLayout {
                    width: parent.parent.width - Kirigami.Units.largeSpacing
                    spacing: 0
                    
                    Repeater {
                        model: connectedDevices
                        
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            
                            Item {
                                Layout.fillWidth: true
                                Layout.preferredHeight: Kirigami.Units.gridUnit * 4
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
                                        
                                        PlasmaComponents.ToolButton {
                                            visible: modelData.connectionType === connectionType.bluetooth && modelData.bluetoothAddress
                                            icon.name: "network-disconnect"
                                            text: "Disconnect"
                                            display: PlasmaComponents.AbstractButton.IconOnly
                                            onClicked: disconnectBluetoothDevice(modelData.bluetoothAddress)
                                            
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
                                        
                                        PlasmaComponents.Label {
                                            text: modelData.percentage + "%"
                                            font.bold: true
                                            Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                                            horizontalAlignment: Text.AlignRight
                                        }
                                    }
                                }
                            }
                            
                            Kirigami.Separator {
                                Layout.fillWidth: true
                                visible: index < connectedDevices.length - 1
                            }
                        }
                    }
                    
                    PlasmaComponents.Label {
                        visible: connectedDevices.length === 0
                        text: "No connected devices with battery info found"
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