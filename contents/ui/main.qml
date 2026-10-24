import QtQuick 2.15
import QtQuick.Layouts
import org.kde.plasma.plasmoid 2.0
import org.kde.plasma.components 3.0 as PlasmaComponents
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami 2.20 as Kirigami
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.notification
import "providers"
import "DeviceUtils.js" as DeviceUtils
import "TestDevices.js" as TestDevices

PlasmoidItem {
    id: root

    // ═══════════════════════════════════════════════════════════════════════
    // PROVIDERS
    // ═══════════════════════════════════════════════════════════════════════

    // Declaration order is the priority order.
    // Vendor-specific sources come first, since each talks to its own devices
    // with maintained per-model knowledge
    // The HID helper is the last-resort direct reader.
    ProviderRegistry {
        id: providers

        CompanionProvider {}
        OpenLinkHubProvider {}
        OpenRazerProvider {}
        KDEConnectProvider {}
        HeadsetControlProvider {}
        SolaarProvider {}
        HIDDevicesProvider {}
        BluezProvider {}
        UPowerProvider {}
    }

    // Debug mode
    property bool debugMode: Plasmoid.configuration.debugMode
    // Debug mode: show the static test devices AND real provider devices
    // (the HID provider simulates a blocked device when debug is on)
    property var allDevices: debugMode ? TestDevices.testDevices.concat(realDevices) : realDevices

    //Notification
    property bool notificationEnabled: Plasmoid.configuration.notificationEnabled !== undefined ? Plasmoid.configuration.notificationEnabled : false
    property var notificationThreshold: Plasmoid.configuration.notificationThreshold !== undefined ? Plasmoid.configuration.notificationThreshold : 20

    // ═══════════════════════════════════════════════════════════════════════
    // UPDATE CHECK
    // ═══════════════════════════════════════════════════════════════════════

    property string latestVersion: ""
    property bool updateAvailable: false
    property bool updateCheckInProgress: false
    property string releaseNotesUrl: "https://github.com/itayavra/batterywatch/releases/latest"

    property bool updateCheckEnabled: Plasmoid.configuration.updateCheckEnabled !== undefined ? Plasmoid.configuration.updateCheckEnabled : true
    property string dismissedUpdateVersion: Plasmoid.configuration.dismissedUpdateVersion || ""

    function versionParts(version) {
        return String(version || "").replace(/^v/i, "").split(".").map(function(part) {
            return parseInt(part, 10) || 0;
        });
    }

    function isNewerVersion(candidate, current) {
        var a = versionParts(candidate);
        var b = versionParts(current);
        var length = Math.max(a.length, b.length);
        for (var i = 0; i < length; i++) {
            var left = a[i] || 0;
            var right = b[i] || 0;
            if (left > right)
                return true;
            if (left < right)
                return false;
        }
        return false;
    }

    // Silently ignores network errors.
    function checkForUpdates() {
        if (!updateCheckEnabled || updateCheckInProgress || !Plasmoid.metaData.version)
            return;

        updateCheckInProgress = true;

        var xhr = new XMLHttpRequest();
        xhr.open("GET", "https://api.github.com/repos/itayavra/batterywatch/releases/latest");
        xhr.timeout = 10000;
        try {
            xhr.setRequestHeader("Accept", "application/vnd.github+json");
        } catch (e) {
        }

        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE)
                return;

            updateCheckInProgress = false;

            if (xhr.status !== 200)
                return;

            try {
                var data = JSON.parse(xhr.responseText);
                var tag = data.tag_name || data.name || "";
                if (!tag || data.draft)
                    return;

                latestVersion = tag.replace(/^v/i, "");
                releaseNotesUrl = data.html_url || releaseNotesUrl;
                updateAvailable = isNewerVersion(latestVersion, Plasmoid.metaData.version);
            } catch (e) {
            }
        };

        xhr.send();
    }

    function openUpdateUrl() {
        Qt.openUrlExternally(releaseNotesUrl);
    }

    function dismissUpdate() {
        if (!latestVersion)
            return;
        Plasmoid.configuration.dismissedUpdateVersion = latestVersion;
    }

    property bool showTooltipUpdate: updateCheckEnabled && updateAvailable && Plasmoid.configuration.updateNotifyTooltip
    property bool showPillUpdate: updateCheckEnabled && updateAvailable && Plasmoid.configuration.updateNotifyInlineMessage
        && dismissedUpdateVersion !== latestVersion

    Timer {
        interval: 24 * 60 * 60 * 1000
        repeat: true
        running: root.updateCheckEnabled
        onTriggered: root.checkForUpdates()
    }


    // ═══════════════════════════════════════════════════════════════════════
    // DEVICE STATE
    // ═══════════════════════════════════════════════════════════════════════

    // Merged devices from all providers
    property var realDevices: DeviceUtils.mergeDevices(providers.devicesByPriority())
    property var hiddenDevices: []
    property var notificationMutedDevices: []
    property var notifiedLowBattery: ({})

    property int visibleDeviceCount: {
        var count = 0;
        for (var i = 0; i < allDevices.length; i++) {
            if (hiddenDevices.indexOf(DeviceUtils.deviceIdentity(allDevices[i])) === -1) {
                count++;
            }
        }
        return count;
    }

    property bool hasVisibleDevices: visibleDeviceCount > 0
    property bool hasAnyDevices: allDevices.length > 0
    property bool allDevicesHidden: hasAnyDevices && !hasVisibleDevices

    // Tray items: flattened list for compact representation
    // For multi-battery devices, only shows batteries with showInTray=true
    property var trayItems: DeviceUtils.buildTrayItems(allDevices, hiddenDevices)

    // The exact command for this blocked device, from the helper (single source
    // of truth). The widget never installs anything itself - the user runs this
    // on their own terms, so there is no root authorization from the widget.
    function unblockCommandFor(device) {
        return device.unblockCommand || "";
    }

    function copyUnblockCommand(device) {
        copyBuffer.text = unblockCommandFor(device);
        copyBuffer.selectAll();
        copyBuffer.copy();
        root.commandCopied = true;
        copyFeedbackTimer.restart();
    }

    // Invisible buffer so copy works in any QML runtime (plasmashell,
    // plasmoidviewer, ...) without relying on a clipboard context property.
    TextEdit {
        id: copyBuffer
        visible: false
    }

    // Brief "Copied" feedback on the copy button
    property bool commandCopied: false
    Timer {
        id: copyFeedbackTimer
        interval: 2000
        onTriggered: root.commandCopied = false
    }

    // Notification
    // Allow multiple notification objects to protect agains race condition when multiple low batteries alerts simultaneously
    Component {
        id: batteryNotificationComponent
        Notification {
            componentName: "plasma_workspace" //this is easier than trying to place .nofifyrc file
            eventId: "notification"
            iconName: "battery-020"
            onClosed: destroy()
        }
    }

    onAllDevicesChanged: {
        checkBatteryNotifications()
    }

    onNotificationEnabledChanged: {
        checkBatteryNotifications()
    }

    onNotificationThresholdChanged: {
        checkBatteryNotifications()
    }

    function checkBatteryNotifications() {
        if (!notificationEnabled) {
            return;
        }

        var result = DeviceUtils.findLowBatteryAlerts(allDevices || [], notificationMutedDevices, notificationThreshold, notifiedLowBattery);
        notifiedLowBattery = result.notified;

        for (var i = 0; i < result.alerts.length; i++) {
            var alert = result.alerts[i];
            batteryNotificationComponent.createObject(root, {
                title: i18n("Low battery"),
                text: i18n("%1%2 has %3% battery remaining",
                    alert.name || i18n("Device"),
                    alert.label ? " (" + alert.label + ")" : "",
                    alert.percentage)
            }).sendEvent();
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // WIDGET CONFIGURATION
    // ═══════════════════════════════════════════════════════════════════════

    preferredRepresentation: compactRepresentation

    toolTipMainText: {
        if (showTooltipUpdate) {
            // i18n: %1 is the version number.
            return i18n("BatteryWatch v%1 (Update available)", Plasmoid.metaData.version);
        }
        // i18n: %1 is the version number.
        return i18n("BatteryWatch v%1", Plasmoid.metaData.version);
    }
    toolTipSubText: {
        // Unable to implement colours, custom hover menu would be necessary
        if (allDevices.length === 0) {
            return i18n("No connected devices");
        }

        var lines = [];
        for (var i = 0; i < allDevices.length; i++) {
            var device = allDevices[i];
            if (hiddenDevices.indexOf(DeviceUtils.deviceIdentity(device)) !== -1)
                continue;
            var line = device.name;

            // Blocked devices have no percentage yet; note why instead
            if (device.blocked === true) {
                line = i18n("%1 - permission needed", line);
            } else if (device.batteries && device.batteries.length > 1) {
                var parts = [];
                for (var j = 0; j < device.batteries.length; j++) {
                    var bat = device.batteries[j];
                    // i18n: %1 can be the device name or, in the case of multiple batteries, the battery label,
                    // or simply the word, ‘Battery’. %2 is the charge percentage value.
                    parts.push(i18n("%1: %2%", bat.label || "Battery", bat.percentage));
                }
                // i18n: Used when there are multiple batteries in a device.
                // %1 is the device name.
                // %2 is the delimited list of the device's batteries and their charge percentages.
                line = i18n("%1 - %2", line,
                // i18n: The delimiter when listing multiple batteries in the same device.
                parts.join(i18n(", ")));
            } else {
                line = i18n("%1: %2%", line, device.percentage);
            }

            lines.push(line);
        }

        return lines.length > 0 ? lines.join("\n") : i18n("All devices hidden");
    }

    Plasmoid.status: {
        if (Plasmoid.userConfiguring) {
            return PlasmaCore.Types.ActiveStatus;
        }
        if (Plasmoid.containment && Plasmoid.containment.corona && Plasmoid.containment.corona.editMode) {
            return PlasmaCore.Types.ActiveStatus;
        }
        return hasAnyDevices ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.HiddenStatus;
    }

    function batteryColor(percentage, charging) {
        // Charging
        if (Plasmoid.configuration.useChargingColor && charging) {
            return Plasmoid.configuration.chargingColor;
        }

        // Zone 2
        if (Plasmoid.configuration.useZoneTwoColor && percentage <= Plasmoid.configuration.zoneTwoThreshold)
            return Plasmoid.configuration.zoneTwoColor;

        // Zone 1
        if (Plasmoid.configuration.useZoneOneColor && percentage <= Plasmoid.configuration.zoneOneThreshold)
            return Plasmoid.configuration.zoneOneColor;

        // Default
        return Plasmoid.configuration.useCustomDefaultColor ? Plasmoid.configuration.customDefaultColor : Kirigami.Theme.textColor;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // HIDDEN DEVICES PERSISTENCE
    // ═══════════════════════════════════════════════════════════════════════

    // Skips the handler during initial binding evaluation.
    property bool updatesReady: false

    Component.onCompleted: {
        loadHiddenDevices();
        loadNotificationMutedDevices();
        checkForUpdates();
        updatesReady = true;
    }

    onUpdateCheckEnabledChanged: {
        if (!updatesReady)
            return;
        Plasmoid.configuration.dismissedUpdateVersion = "";
        if (updateCheckEnabled)
            checkForUpdates();
    }

    function loadHiddenDevices() {
        var saved = Plasmoid.configuration.hiddenDevices;
        if (saved) {
            hiddenDevices = saved.split(",").filter(s => s.length > 0).map(s => DeviceUtils.canonicalSerial(s.trim()));
        } else {
            hiddenDevices = [];
        }
    }

    function loadNotificationMutedDevices() {
        var saved = Plasmoid.configuration.notificationMutedDevices;
        if (saved) {
            notificationMutedDevices = saved.split(",").filter(s => s.length > 0).map(s => DeviceUtils.canonicalSerial(s.trim()));
        } else {
            notificationMutedDevices = [];
        }
    }

    function saveHiddenDevices() {
        Plasmoid.configuration.hiddenDevices = hiddenDevices.join(",");
    }

    function saveNotificationMutedDevices() {
        Plasmoid.configuration.notificationMutedDevices = notificationMutedDevices.join(",");
    }

    function toggleDeviceVisibility(device) {
        var id = DeviceUtils.deviceIdentity(device);
        var index = hiddenDevices.indexOf(id);
        if (index === -1) {
            hiddenDevices.push(id);
        } else {
            hiddenDevices.splice(index, 1);
        }
        hiddenDevices = hiddenDevices.slice();
        saveHiddenDevices();
    }

    function toggleDeviceNotification(device) {
        var id = DeviceUtils.deviceIdentity(device);
        var index = notificationMutedDevices.indexOf(id);
        if (index === -1) {
            notificationMutedDevices.push(id);
        } else {
            notificationMutedDevices.splice(index, 1);
        }

        notificationMutedDevices = notificationMutedDevices.slice();
        saveNotificationMutedDevices();

        // allow the device to notify again, so the user gets an indication the unmute worked
        Object.keys(notifiedLowBattery)
            .filter(key => key.startsWith(id + ":"))
            .forEach(key => delete notifiedLowBattery[key]);
        checkBatteryNotifications();
    }

    // ═══════════════════════════════════════════════════════════════════════
    // COMPACT REPRESENTATION (System Tray)
    // ═══════════════════════════════════════════════════════════════════════

    compactRepresentation: Item {
        property bool inEditMode: {
            if (Plasmoid.userConfiguring)
                return true;
            if (Plasmoid.containment && Plasmoid.containment.corona && Plasmoid.containment.corona.editMode)
                return true;
            return false;
        }

        property bool shouldShow: root.hasVisibleDevices || root.allDevicesHidden || inEditMode

        Layout.minimumWidth: shouldShow ? -1 : 0
        Layout.minimumHeight: shouldShow ? -1 : 0
        Layout.preferredWidth: shouldShow ? (root.hasVisibleDevices ? mainLayout.implicitWidth : placeholderIcon.width) : 0
        Layout.preferredHeight: shouldShow ? (root.hasVisibleDevices ? mainLayout.implicitHeight : placeholderIcon.height) : 0
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

        GridLayout {
            id: mainLayout
            anchors.centerIn: parent
            rowSpacing: Plasmoid.configuration.useCustomTraySpacing ? Plasmoid.configuration.customTraySpacing : Kirigami.Units.smallSpacing
            columnSpacing: Plasmoid.configuration.useCustomTraySpacing ? Plasmoid.configuration.customTraySpacing : Kirigami.Units.smallSpacing
            flow: Plasmoid.formFactor === PlasmaCore.Types.Vertical ? GridLayout.TopToBottom : GridLayout.LeftToRight
            visible: root.hasVisibleDevices

            Repeater {
                model: root.trayItems

                TrayDeviceItem {
                    device: modelData
                    batteryColor: root.batteryColor(modelData.percentage, modelData.charging)
                    flow: mainLayout.flow
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
        Layout.preferredHeight: {
            var baseHeight = Kirigami.Units.gridUnit * 5;
            var deviceHeight = root.allDevices.length * Kirigami.Units.gridUnit * 4;
            var totalHeight = baseHeight + deviceHeight;
            var maxHeight = Kirigami.Units.gridUnit * 17;
            return Math.min(totalHeight, maxHeight);
        }
        Layout.maximumHeight: Kirigami.Units.gridUnit * 35

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents.Label {
                    text: i18n("Device Battery Levels")
                    font.bold: true
                    font.pixelSize: Kirigami.Theme.defaultFont.pixelSize * 1.2
                    Layout.fillWidth: true
                }

                Rectangle {
                    id: updatePill
                    visible: root.showPillUpdate
                    Layout.alignment: Qt.AlignVCenter
                    implicitWidth: updatePillRow.implicitWidth + Kirigami.Units.largeSpacing
                    implicitHeight: updatePillRow.implicitHeight + Kirigami.Units.smallSpacing
                    radius: height / 2
                    color: Qt.rgba(Kirigami.Theme.highlightColor.r,
                                   Kirigami.Theme.highlightColor.g,
                                   Kirigami.Theme.highlightColor.b,
                                   updatePillMouse.containsMouse ? 0.32 : 0.18)

                    // Behind the row so labels stay click-through and the close
                    // button keeps its own click.
                    MouseArea {
                        id: updatePillMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.openUpdateUrl()

                        PlasmaComponents.ToolTip {
                            visible: updatePillMouse.containsMouse && !updatePillDismiss.hovered
                            // i18n: %1 is the newer available version.
                            text: i18n("BatteryWatch v%1 is available — click to download", root.latestVersion)
                        }
                    }

                    RowLayout {
                        id: updatePillRow
                        anchors.centerIn: parent
                        spacing: Kirigami.Units.smallSpacing

                        Kirigami.Icon {
                            source: "download"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: Kirigami.Units.iconSizes.small
                        }

                        PlasmaComponents.Label {
                            // i18n: %1 is the newer available version.
                            text: i18n("Update v%1", root.latestVersion)
                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        }

                        PlasmaComponents.ToolButton {
                            id: updatePillDismiss
                            icon.name: "dialog-close"
                            display: PlasmaComponents.AbstractButton.IconOnly
                            text: i18n("Dismiss")
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: Kirigami.Units.iconSizes.small
                            onClicked: root.dismissUpdate()

                            PlasmaComponents.ToolTip {
                                text: i18n("Hide until the next update")
                            }

                            MouseArea {
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onPressed: mouse.accepted = false
                            }
                        }
                    }
                }

                PlasmaComponents.ToolButton {
                    icon.name: "view-refresh"
                    text: i18n("Refresh")
                    display: PlasmaComponents.AbstractButton.IconOnly

                    PlasmaComponents.ToolTip {
                        text: i18n("Refresh devices")
                    }

                    onClicked: providers.refreshAll()
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
                        model: root.allDevices

                        DeviceRow {
                            device: modelData
                            rowIndex: index
                            rowCount: root.allDevices.length
                            batteryColor: root.batteryColor
                            hidden: root.hiddenDevices.indexOf(DeviceUtils.deviceIdentity(modelData)) !== -1
                            notificationMuted: root.notificationMutedDevices.indexOf(DeviceUtils.deviceIdentity(modelData)) !== -1
                            notificationEnabled: root.notificationEnabled
                            commandCopied: root.commandCopied

                            onDisconnectRequested: {
                                if (typeof modelData.disconnect === "function") {
                                    modelData.disconnect()
                                }
                            }
                            onCopyUnblockCommandRequested: root.copyUnblockCommand(modelData)
                            onToggleVisibilityRequested: root.toggleDeviceVisibility(modelData)
                            onToggleNotificationRequested: root.toggleDeviceNotification(modelData)
                        }
                    }

                    PlasmaComponents.Label {
                        visible: root.allDevices.length === 0
                        text: i18n("No connected devices with battery info found")
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
