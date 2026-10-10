import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils

Item {
    id: root
    visible: false

    property bool headsetControlEnabled: Plasmoid.configuration.enableHeadsetControlIntegration

    property int pollingTime: Plasmoid.configuration.headsetControlPollingTime

    readonly property string command: "/usr/bin/headsetcontrol -b -o json"
    readonly property int wirelessType: 1

    property var devices: []

    function refresh() {
        if (!root.headsetControlEnabled)
            return;
        pollSource.disconnectSource(command);
        pollSource.connectSource(command);
    }

    function parseDevices(output) {
        const parsed = JSON.parse(output);

        if (!parsed.devices || !Array.isArray(parsed.devices)) {
            devices = [];
            return;
        }

        devices = parsed.devices.filter(d => d.status === "success" && d.battery && typeof d.battery.level === "number" && d.battery.level >= 0 && d.battery.level <= 100).map(d => ({
                    name: d.device || d.product || "Gaming Headset",
                    serial: "headsetcontrol-" + (d.id_vendor || "") + ":" + (d.id_product || ""),
                    percentage: d.battery.level,
                    charging: false,
                    blocked: false,
                    type: "headset",
                    icon: DeviceUtils.getIconForType("headset"),
                    connectionType: wirelessType,
                    source: "headsetcontrol",
                    batteries: []
                }));

        console.info("BatteryWatch HeadsetControl: found", devices.length, "device(s)");
    }

    onHeadsetControlEnabledChanged: {
        if (root.headsetControlEnabled) {
            root.refresh();
        } else {
            pollSource.disconnectSource(command);
            retryTimer.stop();
            root.devices = [];
        }
    }

    P5Support.DataSource {
        id: pollSource
        engine: "executable"
        connectedSources: []
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src);

            if (!root.headsetControlEnabled)
                return;
            const exitCode = data["exit code"];
            const stdout = data["stdout"] || "";
            const stderr = data["stderr"] || "";

            if (exitCode !== 0 || !stdout.trim()) {
                console.warn("BatteryWatch HeadsetControl: command failed; exit code:", exitCode, "stderr:", stderr);
                root.devices = [];
                retryTimer.restart();
                return;
            }

            try {
                root.parseDevices(stdout.trim());
            } catch (e) {
                console.warn("BatteryWatch HeadsetControl: JSON parsing failed:", e);
                root.devices = [];
            }

            retryTimer.restart();
        }

        Component.onCompleted: {
            if (root.headsetControlEnabled)
                root.refresh();
        }
    }

    Timer {
        id: retryTimer
        interval: Math.max(5, root.pollingTime) * 1000
        repeat: false

        onTriggered: root.refresh()
    }
}
