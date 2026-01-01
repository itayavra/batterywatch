import QtQuick 2.15
import QtQuick.Layouts
import org.kde.plasma.plasmoid 2.0
import org.kde.plasma.components 3.0 as PlasmaComponents
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami 2.20 as Kirigami
import org.kde.plasma.plasma5support 2.0 as P5Support
import "providers"

PlasmoidItem {
    id: root
    
    // ═══════════════════════════════════════════════════════════════════════
    // PROVIDERS
    // ═══════════════════════════════════════════════════════════════════════
    
    UPowerProvider {
        id: upowerProvider
    }
    
    CompanionProvider {
        id: companionProvider
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // DEVICE STATE
    // ═══════════════════════════════════════════════════════════════════════
    
    // Merged devices from all providers
    property var allDevices: mergeDevices(upowerProvider.devices, companionProvider.devices)
    property var hiddenDevices: []
    
    property int visibleDeviceCount: {
        var count = 0
        for (var i = 0; i < allDevices.length; i++) {
            if (hiddenDevices.indexOf(allDevices[i].serial) === -1) {
                count++
            }
        }
        return count
    }
    
    property bool hasVisibleDevices: visibleDeviceCount > 0
    property bool hasAnyDevices: allDevices.length > 0
    property bool allDevicesHidden: hasAnyDevices && !hasVisibleDevices
    
    // Tray items: flattened list for compact representation
    // For multi-battery devices, only shows batteries with showInTray=true
    property var trayItems: buildTrayItems(allDevices, hiddenDevices)
    
    function buildTrayItems(devices, hidden) {
        var items = []
        for (var i = 0; i < devices.length; i++) {
            var device = devices[i]
            if (hidden.indexOf(device.serial) !== -1) continue
            
            // Multi-battery device (e.g., AirPods)
            if (device.batteries && device.batteries.length > 1) {
                for (var j = 0; j < device.batteries.length; j++) {
                    var bat = device.batteries[j]
                    
                    // Skip batteries marked as not for tray (e.g., Case)
                    if (bat.showInTray === false) continue
                    
                    items.push({
                        icon: device.icon,
                        percentage: bat.percentage,
                        label: bat.label,
                        deviceSerial: device.serial
                    })
                }
            } else {
                // Single battery device
                items.push({
                    icon: device.icon,
                    percentage: device.percentage,
                    label: null,
                    deviceSerial: device.serial
                })
            }
        }
        return items
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // DEVICE MERGING
    // ═══════════════════════════════════════════════════════════════════════
    
    // Merge devices from multiple providers, avoiding duplicates
    function mergeDevices(upowerDevices, companionDevices) {
        var merged = []
        var seenIds = {}
        
        // Add UPower devices first (they have priority)
        for (var i = 0; i < upowerDevices.length; i++) {
            var device = upowerDevices[i]
            var id = device.serial || device.objectPath || ""
            if (id && !seenIds[id]) {
                merged.push(device)
                seenIds[id] = true
            }
        }
        
        // Add companion devices (skip duplicates)
        for (var j = 0; j < companionDevices.length; j++) {
            var device = companionDevices[j]
            var id = device.serial || ""
            if (id && !seenIds[id]) {
                merged.push(device)
                seenIds[id] = true
            }
        }
        
        // Sort by name
        merged.sort(function(a, b) {
            var nameA = a.name || ""
            var nameB = b.name || ""
            return nameA.localeCompare(nameB)
        })
        
        return merged
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // WIDGET CONFIGURATION
    // ═══════════════════════════════════════════════════════════════════════
    
    preferredRepresentation: compactRepresentation
    
    toolTipMainText: "BatteryWatch v" + Plasmoid.metaData.version
    toolTipSubText: {
        if (allDevices.length === 0) {
            return "No connected devices"
        }
        
        var lines = []
        for (var i = 0; i < allDevices.length; i++) {
            var device = allDevices[i]
            if (hiddenDevices.indexOf(device.serial) === -1) {
                var line = device.name
                
                // Multi-battery display
                if (device.batteries && device.batteries.length > 1) {
                    var parts = []
                    for (var j = 0; j < device.batteries.length; j++) {
                        var bat = device.batteries[j]
                        parts.push((bat.label || "Battery") + ": " + bat.percentage + "%")
                    }
                    line += " - " + parts.join(", ")
                } else {
                    line += ": " + device.percentage + "%"
                }
                
                lines.push(line)
            }
        }
        
        return lines.length > 0 ? lines.join("\n") : "All devices hidden"
    }
    
    Plasmoid.status: {
        if (Plasmoid.userConfiguring) {
            return PlasmaCore.Types.ActiveStatus
        }
        if (Plasmoid.containment && Plasmoid.containment.corona && Plasmoid.containment.corona.editMode) {
            return PlasmaCore.Types.ActiveStatus
        }
        return hasAnyDevices ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.HiddenStatus
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // HIDDEN DEVICES PERSISTENCE
    // ═══════════════════════════════════════════════════════════════════════
    
    Component.onCompleted: {
        loadHiddenDevices()
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
        hiddenDevices = hiddenDevices.slice()
        saveHiddenDevices()
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // DEVICE ACTIONS
    // ═══════════════════════════════════════════════════════════════════════
    
    function refreshDevices() {
        upowerProvider.refresh()
        companionProvider.refresh()
    }
    
    P5Support.DataSource {
        id: bluetoothCtlSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName)
            Qt.callLater(refreshDevices)
        }
    }
    
    function disconnectBluetoothDevice(bluetoothAddress) {
        if (bluetoothAddress) {
            bluetoothCtlSource.connectSource("bluetoothctl disconnect " + bluetoothAddress)
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // COMPACT REPRESENTATION (System Tray)
    // ═══════════════════════════════════════════════════════════════════════
    
    compactRepresentation: Item {
        property bool inEditMode: {
            if (Plasmoid.userConfiguring) return true
            if (Plasmoid.containment && Plasmoid.containment.corona && Plasmoid.containment.corona.editMode) return true
            return false
        }
        
        property bool shouldShow: root.hasVisibleDevices || root.allDevicesHidden || inEditMode
        
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
                model: root.trayItems
                
                RowLayout {
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
    
    // ═══════════════════════════════════════════════════════════════════════
    // FULL REPRESENTATION (Popup)
    // ═══════════════════════════════════════════════════════════════════════
    
    fullRepresentation: Item {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 25
        Layout.preferredWidth: Kirigami.Units.gridUnit * 30
        Layout.minimumHeight: Kirigami.Units.gridUnit * 8
        Layout.preferredHeight: Math.min(
            Kirigami.Units.gridUnit * 5 + root.allDevices.length * Kirigami.Units.gridUnit * 4,
            Kirigami.Units.gridUnit * 17
        )
        Layout.maximumHeight: Kirigami.Units.gridUnit * 17
        
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.largeSpacing
            
            // Header
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
                    display: PlasmaComponents.AbstractButton.IconOnly
                    PlasmaComponents.ToolTip { text: "Refresh devices" }
                    onClicked: refreshDevices()
                }
            }
            
            // Device list
            PlasmaComponents.ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                PlasmaComponents.ScrollBar.horizontal.policy: PlasmaComponents.ScrollBar.AlwaysOff
                
                ColumnLayout {
                    width: parent.parent.width - Kirigami.Units.largeSpacing
                    spacing: 0
                    
                    Repeater {
                        model: root.allDevices
                        
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            
                            // Device row with hover detection
                            MouseArea {
                                id: rowHoverArea
                                Layout.fillWidth: true
                                Layout.preferredHeight: Kirigami.Units.gridUnit * 4
                                Layout.topMargin: Kirigami.Units.smallSpacing
                                Layout.bottomMargin: Kirigami.Units.smallSpacing
                                hoverEnabled: true
                                
                                RowLayout {
                                    anchors.fill: parent
                                    spacing: Kirigami.Units.smallSpacing
                                    
                                    // Clickable device icon (visibility toggle)
                                    MouseArea {
                                        id: iconArea
                                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                                        Layout.alignment: Qt.AlignVCenter
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: root.toggleDeviceVisibility(modelData.serial)
                                        
                                        Kirigami.Icon {
                                            anchors.fill: parent
                                            source: modelData.icon || "battery-symbolic"
                                            opacity: root.hiddenDevices.indexOf(modelData.serial) !== -1 ? 0.4 : 1.0
                                        }
                                        
                                        PlasmaComponents.ToolTip {
                                            visible: iconArea.containsMouse
                                            text: root.hiddenDevices.indexOf(modelData.serial) !== -1 ? "Show in tray" : "Hide from tray"
                                        }
                                    }
                                    
                                    // Device info (2 rows: name, MAC)
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.alignment: Qt.AlignVCenter
                                        spacing: 2
                                        
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: Kirigami.Units.smallSpacing
                                            
                                            PlasmaComponents.Label {
                                                text: modelData.name || "Unknown Device"
                                                font.bold: true
                                                elide: Text.ElideRight
                                            }
                                            
                                            // Disconnect button (right of name, visible on hover only)
                                            MouseArea {
                                                id: disconnectArea
                                                visible: rowHoverArea.containsMouse && modelData.connectionType === 2 && modelData.bluetoothAddress
                                                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                                Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                                Layout.alignment: Qt.AlignVCenter
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: root.disconnectBluetoothDevice(modelData.bluetoothAddress)
                                                
                                                Kirigami.Icon {
                                                    anchors.fill: parent
                                                    source: "network-disconnect"
                                                }
                                                
                                                PlasmaComponents.ToolTip {
                                                    visible: disconnectArea.containsMouse
                                                    text: "Disconnect device"
                                                }
                                            }
                                            
                                            // Spacer to push battery info to the right
                                            Item { Layout.fillWidth: true }
                                        }
                                        
                                        PlasmaComponents.Label {
                                            text: modelData.serial || ""
                                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                                            color: Kirigami.Theme.disabledTextColor
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                            visible: modelData.serial
                                        }
                                    }
                                    
                                    // Battery info (right side)
                                    RowLayout {
                                        Layout.alignment: Qt.AlignVCenter
                                        spacing: Kirigami.Units.smallSpacing
                                        
                                        // Store device reference for nested Repeater
                                        property var device: modelData
                                        
                                        // Batteries with labels (e.g., L:100%⚡ R:90% C:60%)
                                        Repeater {
                                            model: (parent.device.batteries && parent.device.batteries.length > 0) ? parent.device.batteries : []
                                            
                                            PlasmaComponents.Label {
                                                text: {
                                                    var bat = modelData
                                                    var charging = bat.charging ? "⚡" : ""
                                                    if (bat.label) {
                                                        return bat.label.charAt(0) + ":" + bat.percentage + "%" + charging
                                                    } else {
                                                        return bat.percentage + "%" + charging
                                                    }
                                                }
                                                font.bold: true
                                            }
                                        }
                                        
                                        // Fallback: no batteries array, just percentage
                                        PlasmaComponents.Label {
                                            visible: !parent.device.batteries || parent.device.batteries.length === 0
                                            text: parent.device.percentage + "%"
                                            font.bold: true
                                            Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                                            horizontalAlignment: Text.AlignRight
                                        }
                                    }
                                }
                            }
                            
                            // Separator between devices
                            Kirigami.Separator {
                                Layout.fillWidth: true
                                visible: index < root.allDevices.length - 1
                            }
                        }
                    }
                    
                    // Empty state
                    PlasmaComponents.Label {
                        visible: root.allDevices.length === 0
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
