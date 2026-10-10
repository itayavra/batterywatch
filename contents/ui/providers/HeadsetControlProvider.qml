import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import "../DeviceUtils.js" as DeviceUtils

Item {
    id: root
    visible: false

    readonly property string command: "/usr/bin/headsetcontrol -b -o json"
    readonly property int wirelessType: 1

    property var devices: []

    function refresh() {
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

    P5Support.DataSource {
        id: pollSource
        engine: "executable"
        connectedSources: []
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src);

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

        Component.onCompleted: root.refresh()
    }

    Timer {
        id: retryTimer
        interval: 30000
        repeat: false

        onTriggered: root.refresh()
    }
}
