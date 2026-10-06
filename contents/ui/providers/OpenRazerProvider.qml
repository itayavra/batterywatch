import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils
import "../GVariant.js" as GVariant

// Razer device provider
// Based on UPowerProvider.qml
// Author: TheDogORB <thedogorb@proton.me>

Item {
    id: root
    visible: false

    // org.razer is on the session bus
    readonly property string getDeviceListCmd: "gdbus call --session --dest org.razer --object-path /org/razer --method razer.devices.getDevices"

    property bool daemonUnavailable: false

    // Can't test this as I don't have means to connect mouse to PC via Bluetooth
    // but based on what I found on the openrazer github, Bluetooth is currently
    // unsupported, and devices connected via this mean are handled by kernel/OS
    // https://github.com/openrazer/openrazer/issues?q=state%3Aopen%20label%3ABluetooth

    // 0 = wired; 1 = wireless (dongle); 2 = bluetooth
    readonly property int wirelessType: 1

    // Data passed to the applet
    property var devices: []

    property var deviceData: ({})
    property var knownDevices: ({})
    readonly property var emptyList: []

    property bool razerEnabled: Plasmoid.configuration.enableOpenRazerIntegration

    onRazerEnabledChanged: {
        if (!razerEnabled) {
            devices = [];
            deviceData = {};
            knownDevices = {};
        } else {
            refresh();
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // GUI RELATED FUNCTIONS
    // ═══════════════════════════════════════════════════════════════════════

    // Refresh via "refresh" button in the GUI
    function refresh() {
        listSource.disconnectSource(getDeviceListCmd);
        listSource.connectSource(getDeviceListCmd);

        for (let id in deviceData) {
            fetchPowerInfo(id);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // HELPER FUNCTIONS
    // ═══════════════════════════════════════════════════════════════════════

    function deviceCmd(id, method) {
        return `gdbus call --session --dest org.razer --object-path /org/razer/device/${id} --method razer.device.${method}`;
    }

    // Updates the device model from the current internal state
    function updateOpenRazerDevices() {
        let result = [];

        for (let id in deviceData) {
            let d = deviceData[id];

            // Filter out devices w/o a battery or disconnected devices
            //
            // When device gets DCed but its dongle is still connected, name,
            // type vars still persists but battery charge (and firmware version)
            // is set to 0 (and v0.0 respectively) when device is powered off
            //
            // openrazer can report battery being 100% charged up to 30s after
            // connecting a device
            if (typeof d.battery !== "number") {
                continue;
            }
            if (d.firmware === undefined || d.firmware === "v0.0") {
                continue;
            }
            result.push({
                name: d.name || i18n("Unknown Razer Device"),
                serial: id,
                percentage: d.battery,
                charging: d.charging === true,
                type: d.type || "unknown",
                icon: DeviceUtils.getIconForType(d.type || "unknown"),
                connectionType: wirelessType,   // Always wireless, openRazer doesn't support Bluetooth devices -> handled by kernel
                source: "openrazer",
                batteries: emptyList           // OpenRazer does not support multiple batteries, only razer.device.power.getBattery() is exposed
            });
        }

        // Sorts devices alphabetically, name is always d.name or Unknown Razer Device
        result.sort((a, b) => a.name.localeCompare(b.name));

        // Skips UI redraw if nothing has changed
        if (result.length === devices.length) {
            let changed = false;
            for (let i = 0; i < result.length; i++) {
                const r = result[i], d = devices[i];
                if (
                    r.serial !== d.serial || 
                    r.percentage !== d.percentage ||
                    r.charging !== d.charging || 
                    r.name !== d.name
                    ) {
                    changed = true;
                    break;
                }
            }
            if (!changed)
                return;
        }

        devices = result;
    }

    function fetchNameAndType(id) {
        detailsSource.connectSource(deviceCmd(id, "misc.getDeviceName"));
        detailsSource.connectSource(deviceCmd(id, "misc.getDeviceType"));
    }

    function fetchPowerInfo(id) {
        if (!deviceData[id])
            return;
        batterySource.connectSource(deviceCmd(id, "power.getBattery"));
        chargingSource.connectSource(deviceCmd(id, "power.isCharging"));
        detailsSource.connectSource(deviceCmd(id, "misc.getFirmware"));
    }

    // ═══════════════════════════════════════════════════════════════════════
    // DEVICE DISCOVERY
    // ═══════════════════════════════════════════════════════════════════════

    // openrazer lacks device added/removed signal -> instead devices are polled
    // periodically razer.devices.getDevices function
    // Result is then diffed against list of devices known in the last run of the
    // function -> new/disconnected devices are found
    P5Support.DataSource {
        id: listSource
        engine: "executable"
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src);

            if (!root.razerEnabled)
                return;

            // a failed call used to look exactly like "no Razer devices"
            if (data["exit code"] !== 0) {
                if (Object.keys(root.knownDevices).length > 0) {
                    root.devices = [];
                    root.deviceData = {};
                    root.knownDevices = {};
                }
                if (!root.daemonUnavailable) {
                    root.daemonUnavailable = true;
                    // i18n: %1 is the error message of the D-Bus call.
                    console.log(i18n("BatteryWatch: OpenRazer daemon unavailable (%1)", (data.stderr || "").trim()));
                }
                return;
            }
            root.daemonUnavailable = false;

            let ids;
            try {
                ids = GVariant.parseReply(data.stdout);
                if (!Array.isArray(ids) || !ids.every(id => typeof id === "string"))
                    throw new Error("expected an array of device ids");
            } catch (error) {
                console.warn(i18n("BatteryWatch: unreadable OpenRazer reply (%1)", error.message));
                return;
            }

            let current = {};
            ids.forEach(id => {
                current[id] = true;

                if (!root.knownDevices[id]) {
                    root.deviceData[id] = {
                        name: "",
                        type: "",
                        firmware: undefined,
                        battery: undefined,
                        charging: false
                    };

                    root.fetchNameAndType(id);
                    root.fetchPowerInfo(id);
                }
            });

            // Remove unresponsive/stale devices
            for (let id in root.knownDevices) {
                if (!current[id]) {
                    delete root.deviceData[id];
                }
            }

            root.knownDevices = current;
            Qt.callLater(root.updateOpenRazerDevices);
        }

        Component.onCompleted: {
            if (root.razerEnabled)
                connectSource(root.getDeviceListCmd);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // BATTERY HANDLING
    // ═══════════════════════════════════════════════════════════════════════

    // Updates percentage (battery charge) values via razer.device.power.getBattery
    // if the func exists for a device -> func doesn't exist for wired devices
    P5Support.DataSource {
        id: batterySource
        engine: "executable"
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src);

            if (!src.includes("/device/"))
                return;
            const id = src.split("/device/")[1].split(" ")[0];
            if (!root.deviceData[id])
                return;

            // Non-battery device
            if ((data.stderr || "").includes("UnknownMethod")) {
                delete root.deviceData[id];
                Qt.callLater(root.updateOpenRazerDevices);
                return;
            }

            if (data["exit code"] !== 0)
                return;

            // 0 is handled in updateOpenRazerDevices()
            let raw;
            try {
                raw = GVariant.parseReply(data.stdout);
                if (typeof raw !== "number" || !Number.isFinite(raw))
                    throw new Error("expected a finite number");
            } catch (error) {
                console.warn(i18n("BatteryWatch: unreadable OpenRazer reply (%1)", error.message));
                return;
            }
            root.deviceData[id].battery = Math.round(Math.max(0, Math.min(100, raw)));

            Qt.callLater(root.updateOpenRazerDevices);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // CHARGING HANDLING
    // ═══════════════════════════════════════════════════════════════════════

    // Updates isCharging to true/false via razer.device.power.isCharging
    P5Support.DataSource {
        id: chargingSource
        engine: "executable"
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src);

            if (!src.includes("/device/"))
                return;
            const id = src.split("/device/")[1].split(" ")[0];
            if (!root.deviceData[id])
                return;

            if (data["exit code"] !== 0)
                return;
            let charging;
            try {
                charging = GVariant.parseReply(data.stdout);
                if (typeof charging !== "boolean")
                    throw new Error("expected a boolean");
            } catch (error) {
                console.warn(i18n("BatteryWatch: unreadable OpenRazer reply (%1)", error.message));
                return;
            }
            root.deviceData[id].charging = charging;

            Qt.callLater(root.updateOpenRazerDevices);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // META DATA
    // ═══════════════════════════════════════════════════════════════════════

    P5Support.DataSource {
        id: detailsSource
        engine: "executable"
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src);

            if (!src.includes("/device/"))
                return;
            const id = src.split("/device/")[1].split(" ")[0];
            if (!root.deviceData[id]) {
                return;
            }
            // name/type fetched once on connect
            // ignore errors to avoid overwriting with empty/garbage values
            if (data["exit code"] !== 0 || (data.stderr || "").trim().length > 0) {
                return;
            }
            let value;
            try {
                value = GVariant.parseReply(data.stdout);
                if (typeof value !== "string")
                    throw new Error("expected a string");
            } catch (error) {
                console.warn(i18n("BatteryWatch: unreadable OpenRazer reply (%1)", error.message));
                return;
            }
            if (value.length === 0)
                return;

            if (src.includes("misc.getDeviceName")) {
                root.deviceData[id].name = value;
            } else if (src.includes("misc.getDeviceType")) {
                root.deviceData[id].type = value;
            } else if (src.includes("misc.getFirmware")) {
                root.deviceData[id].firmware = value;
            }

            Qt.callLater(root.updateOpenRazerDevices);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // TIMERS
    // ═══════════════════════════════════════════════════════════════════════

    // Periodic 'device discovery' scan + battery refresh
    Timer {
        interval: Plasmoid.configuration.openRazerPollingTime * 1000
        running: root.razerEnabled
        repeat: true
        onTriggered: root.refresh()
    }
}
