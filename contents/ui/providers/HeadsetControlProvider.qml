import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils

Item {
    id: root
    visible: false

    property bool headsetControlEnabled: Plasmoid.configuration.enableHeadsetControlIntegration
    property int pollingTime: Plasmoid.configuration.headsetControlPollingTime

    readonly property string command: "headsetcontrol -b -o json"
    readonly property int wirelessType: 1

    property var devices: []

    // Match SolaarProvider.qml's failure backoff and logging behavior.
    property int failureBackoff: 1
    property bool headsetControlUnavailable: false

    function refresh() {
        if (!root.headsetControlEnabled)
            return;

        pollSource.disconnectSource(command);
        pollSource.connectSource(command);
    }

    function parseDevices(output) {
        const parsed = JSON.parse(output);

        if (!parsed.devices || !Array.isArray(parsed.devices))
            throw new Error("Missing or invalid devices array");

        root.devices = parsed.devices.filter(d => {
            if (!d || (d.status !== "success" && d.status !== "partial") || !d.battery)
                return false;

            const level = d.battery.level;
            const hasValidLevel = typeof level === "number" && level >= 0 && level <= 100;
            const isCharging = d.battery.status === "BATTERY_CHARGING";

            // Some headsets report -1 while charging.
            return hasValidLevel || isCharging;
        }).map(d => {
            const level = d.battery.level;
            const hasValidLevel = typeof level === "number" && level >= 0 && level <= 100;

            return {
                name: d.device || d.product || i18n("Unknown Device"),
                serial: (d.id_vendor || "") + ":" + (d.id_product || ""),
                percentage: hasValidLevel ? level : null,
                charging: d.battery.status === "BATTERY_CHARGING" ? true : d.battery.status === "BATTERY_AVAILABLE" ? false : null,
                blocked: false,
                type: "headset",
                icon: DeviceUtils.getIconForType("headset"),
                connectionType: wirelessType,
                source: "headsetcontrol",
                batteries: []
            };
        });
    }

    onHeadsetControlEnabledChanged: {
        if (root.headsetControlEnabled) {
            root.failureBackoff = 1;
            root.headsetControlUnavailable = false;
            root.refresh();
        } else {
            pollSource.disconnectSource(command);
            retryTimer.stop();
            root.devices = [];
            root.failureBackoff = 1;
            root.headsetControlUnavailable = false;
        }
    }

    onPollingTimeChanged: {
        if (root.headsetControlEnabled)
            retryTimer.restart();
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

            let parsedSuccessfully = false;

            // A non-zero exit code can still accompany valid JSON, including
            // an empty devices array. The JSON payload determines success.
            if (stdout.trim()) {
                try {
                    root.parseDevices(stdout.trim());
                    parsedSuccessfully = true;
                } catch (e) {
                    root.devices = [];
                    if (Plasmoid.configuration.debugMode)
                        console.warn("BatteryWatch HeadsetControl: invalid JSON:", e);
                }
            } else {
                root.devices = [];
            }

            if (parsedSuccessfully) {
                root.failureBackoff = 1;
                root.headsetControlUnavailable = false;
            } else {
                root.failureBackoff = 6;

                if (!root.headsetControlUnavailable) {
                    console.warn("BatteryWatch HeadsetControl: command failed or returned invalid JSON; exit code:", exitCode, "stderr:", stderr);
                    root.headsetControlUnavailable = true;
                }
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
        interval: Math.max(5, root.pollingTime) * 1000 * root.failureBackoff
        repeat: false

        onTriggered: root.refresh()
    }
}
