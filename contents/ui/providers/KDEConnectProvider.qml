import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils
import "../GVariant.js" as GVariant

Item {
    id: root
    visible: false

    property var devices: []
    property var deviceData: ({})
    property var knownDevices: ({})
    readonly property var emptyList: []

    property bool kdeConnectEnabled: Plasmoid.configuration.enableKDEConnectIntegration

    onKdeConnectEnabledChanged: {
        if (!kdeConnectEnabled) {
            devices = []
            deviceData = {}
            knownDevices = {}
        } else {
            refresh()
        }
    }

    // gdbus call for listing devices — avoids qdbus/qdbus6 availability issues on Qt5 vs Qt6 systems
    readonly property string listCmd: "gdbus call --session --dest org.kde.kdeconnect --object-path /modules/kdeconnect --method org.kde.kdeconnect.daemon.devices true true 2>/dev/null"

    // gdbus GetAll fetches all properties in one call; lighter than qdbus (no Qt startup)
    function propsCmd(id) {
        return `gdbus call --session --dest org.kde.kdeconnect --object-path /modules/kdeconnect/devices/${id} --method org.freedesktop.DBus.Properties.GetAll org.kde.kdeconnect.device 2>/dev/null`
    }

    // Battery plugin is a sub-object at /devices/ID/battery, not the device root
    function batteryCmd(id) {
        return `gdbus call --session --dest org.kde.kdeconnect --object-path /modules/kdeconnect/devices/${id}/battery --method org.freedesktop.DBus.Properties.GetAll org.kde.kdeconnect.device.battery 2>/dev/null`
    }

    function refresh() {
        listSource.disconnectSource(listCmd)
        listSource.connectSource(listCmd)
        for (let id in deviceData)
            refreshBattery(id)
    }

    // Full fetch (name + type + battery) — used only on first discovery
    function fetchDeviceData(id) {
        propsSource.connectSource(propsCmd(id))
        batterySource.connectSource(batteryCmd(id))
    }

    // Battery-only refresh — used on periodic polls for known devices
    function refreshBattery(id) {
        batterySource.connectSource(batteryCmd(id))
    }

    function updateDevices() {
        let result = []
        for (let id in deviceData) {
            const d = deviceData[id]
            if (d.charge < 0) continue
            result.push({
                name: d.name || id,
                serial: id,
                percentage: d.charge,
                type: d.type || "phone",
                icon: DeviceUtils.getIconForType(d.type || "phone"),
                connectionType: 1,
                source: "kdeconnect",
                batteries: emptyList,
                charging: d.charging === true,
                model: null,
                objectPath: null,
                nativePath: null,
                bluetoothAddress: null,
                disconnect: () => unpairSource.connectSource(`gdbus call --session --dest org.kde.kdeconnect --object-path /modules/kdeconnect/devices/${id} --method org.kde.kdeconnect.device.unpair 2>/dev/null`),
                disconnectTooltip: i18n("Unpair KDE Connect device")
            })
        }
        result.sort((a, b) => (a.name || "").localeCompare(b.name || ""))

        if (result.length === devices.length) {
            let changed = false
            for (let i = 0; i < result.length; i++) {
                const r = result[i], d = devices[i]
                if (r.serial !== d.serial || r.percentage !== d.percentage || r.charging !== d.charging || r.name !== d.name) {
                    changed = true
                    break
                }
            }
            if (!changed) return
        }
        devices = result
    }

    // ═══════════════════════════════════════════════════════════════════════
    // DEVICE DISCOVERY
    // ═══════════════════════════════════════════════════════════════════════

    P5Support.DataSource {
        id: listSource
        engine: "executable"
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src)

            if (!root.kdeConnectEnabled) return

            if (data["exit code"] !== 0) {
                if (Object.keys(root.knownDevices).length > 0) {
                    root.devices = []
                    root.deviceData = {}
                    root.knownDevices = {}
                    console.log(i18n("BatteryWatch: KDE Connect daemon unavailable"))
                }
                return
            }

            // gdbus outputs GVariant format: (['id1', 'id2'],)
            let ids;
            try {
                ids = GVariant.parseReply(data.stdout);
                if (!Array.isArray(ids) || !ids.every(id => typeof id === "string"))
                    throw new Error("expected an array of device ids");
            } catch (error) {
                console.warn(i18n("BatteryWatch: unreadable KDE Connect reply (%1)", error.message));
                return;
            }

            const wasEmpty = Object.keys(root.knownDevices).length === 0
            let current = {}

            ids.forEach(id => {
                current[id] = true
                if (!root.knownDevices[id]) {
                    root.deviceData[id] = { name: "", type: "", charge: -1, charging: false }
                    root.fetchDeviceData(id)
                }
            })

            for (let id in root.knownDevices) {
                if (!current[id]) delete root.deviceData[id]
            }

            root.knownDevices = current

            if (wasEmpty && ids.length > 0)
                console.log(i18n("BatteryWatch: KDE Connect daemon connected"))

            Qt.callLater(root.updateDevices)
        }

        Component.onCompleted: {
            if (root.kdeConnectEnabled)
                connectSource(root.listCmd)
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // DEVICE PROPERTIES (name, type) via GetAll
    // ═══════════════════════════════════════════════════════════════════════

    P5Support.DataSource {
        id: propsSource
        engine: "executable"
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src)
            const match = src.match(/\/devices\/([^\/\s]+)/)
            if (!match) return
            const id = match[1]
            if (!root.deviceData[id]) return
            if (data["exit code"] !== 0) return

            // gdbus GetAll output: ({'name': <'Phone'>, 'type': <'phone'>, ...},)
            let properties;
            try {
                properties = GVariant.parseReply(data.stdout);
                if (!properties || typeof properties !== "object" || Array.isArray(properties))
                    throw new Error("expected a property dictionary");
                if (properties.name !== undefined && typeof properties.name !== "string")
                    throw new Error("expected 'name' to be a string");
                if (properties.type !== undefined && typeof properties.type !== "string")
                    throw new Error("expected 'type' to be a string");
            } catch (error) {
                console.warn(i18n("BatteryWatch: unreadable KDE Connect reply (%1)", error.message));
                return;
            }

            // A missing property keeps its previous value
            if (typeof properties.name === "string") root.deviceData[id].name = properties.name
            if (typeof properties.type === "string") root.deviceData[id].type = properties.type
            Qt.callLater(root.updateDevices)
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // BATTERY (charge, isCharging) via GetAll
    // ═══════════════════════════════════════════════════════════════════════

    P5Support.DataSource {
        id: batterySource
        engine: "executable"
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src)
            const match = src.match(/\/devices\/([^\/\s]+)/)
            if (!match) return
            const id = match[1]
            if (!root.deviceData[id]) return
            if (data["exit code"] !== 0) return

            // gdbus GetAll output: ({'charge': <75>, 'isCharging': <false>},)
            let properties;
            try {
                properties = GVariant.parseReply(data.stdout);
                if (!properties || typeof properties !== "object" || Array.isArray(properties))
                    throw new Error("expected a property dictionary");
                if (properties.charge !== undefined
                    && (typeof properties.charge !== "number" || !Number.isFinite(properties.charge)))
                    throw new Error("expected 'charge' to be a finite number");
                if (properties.isCharging !== undefined && typeof properties.isCharging !== "boolean")
                    throw new Error("expected 'isCharging' to be a boolean");
            } catch (error) {
                console.warn(i18n("BatteryWatch: unreadable KDE Connect reply (%1)", error.message));
                return;
            }

            // A missing property keeps its previous value
            if (typeof properties.charge === "number" && Number.isFinite(properties.charge))
                root.deviceData[id].charge = properties.charge
            if (typeof properties.isCharging === "boolean")
                root.deviceData[id].charging = properties.isCharging
            Qt.callLater(root.updateDevices)
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // UNPAIR
    // ═══════════════════════════════════════════════════════════════════════

    P5Support.DataSource {
        id: unpairSource
        engine: "executable"
        interval: 0
        onNewData: (src, data) => {
            disconnectSource(src)
            Qt.callLater(root.refresh)
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // TIMER
    // ═══════════════════════════════════════════════════════════════════════

    Timer {
        interval: Plasmoid.configuration.kdeConnectPollingTime * 1000
        running: root.kdeConnectEnabled
        repeat: true
        onTriggered: root.refresh()
    }
}
