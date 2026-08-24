import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils

// HeadsetControl provider: reads battery from gaming headsets via the
// headsetcontrol CLI tool (https://github.com/Sapd/HeadsetControl).
// Covers SteelSeries, HyperX, Corsair, ROCCAT, Audeze, Sony and others
// that are not handled by the HID provider.
//
// Requires headsetcontrol to be installed and accessible in PATH.
// Devices that overlap with the HID provider (Logitech) are deduplicated
// by the merge layer since HID has higher priority.
Item {
    id: root
    visible: false

    readonly property string binaryCmd: "headsetcontrol -o json"

    property var devices: []
    property var pendingData: null
    readonly property var emptyList: []

    property bool hcEnabled: Plasmoid.configuration.enableHeadsetControlIntegration

    // Track whether the binary was found, so we can poll slowly when absent
    property bool binaryAvailable: false

    onHcEnabledChanged: {
        if (!hcEnabled) {
            devices = []
            pendingData = null
            retryTimer.stop()
        } else {
            refresh()
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // GUI RELATED FUNCTIONS
    // ═══════════════════════════════════════════════════════════════════════

    function refresh() {
        pollSource.disconnectSource(binaryCmd)
        pollSource.connectSource(binaryCmd)
    }

    // ═══════════════════════════════════════════════════════════════════════
    // HELPER FUNCTIONS
    // ═══════════════════════════════════════════════════════════════════════

    function updateDevices() {
        const parsed = root.pendingData
        if (!parsed) return

        const result = parsed
            .filter(d => {
                if (!d.battery) return false
                const status = d.battery.status
                return status === "BATTERY_AVAILABLE" || status === "BATTERY_CHARGING"
            })
            .map(d => ({
                name: d.device || i18n("Unknown Headset"),
                serial: "hc-" + d.id_vendor + ":" + d.id_product,
                percentage: Math.max(0, d.battery.level || 0),
                charging: d.battery.status === "BATTERY_CHARGING",
                type: "headset",
                icon: DeviceUtils.getIconForType("headset"),
                connectionType: 1,
                source: "headsetcontrol",
                batteries: emptyList,
            }))

        if (result.length === devices.length) {
            const oldMap = {}
            for (const d of devices)
                oldMap[d.serial] = d

            const changed = result.some(n => {
                const o = oldMap[n.serial]
                return !o || o.percentage !== n.percentage || o.charging !== n.charging
            })
            if (!changed) return
        }

        devices = result
    }

    // ═══════════════════════════════════════════════════════════════════════
    // POLLING
    // ═══════════════════════════════════════════════════════════════════════

    P5Support.DataSource {
        id: pollSource
        engine: "executable"
        connectedSources: []
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src)

            if (!root.hcEnabled) {
                root.devices = []
                return
            }

            if (!data.stdout || data["exit code"] !== 0) {
                if (root.binaryAvailable) {
                    root.binaryAvailable = false
                    root.devices = []
                    console.log(i18n("BatteryWatch: headsetcontrol binary not found"))
                }
                retryTimer.restart()
                return
            }

            try {
                const parsed = JSON.parse(data.stdout.trim())
                if (!parsed || !Array.isArray(parsed.devices)) {
                    if (root.devices.length > 0)
                        root.devices = []
                    retryTimer.restart()
                    return
                }
                root.pendingData = parsed.devices
                if (!root.binaryAvailable) {
                    root.binaryAvailable = true
                    console.log(i18n("BatteryWatch: headsetcontrol connected"))
                }
                Qt.callLater(root.updateDevices)
            } catch (e) {
                console.warn(i18n("BatteryWatch: Failed to parse headsetcontrol output:"), e)
                root.devices = []
            }
            retryTimer.restart()
        }

        Component.onCompleted: {
            if (root.hcEnabled)
                root.refresh()
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // POLLING TIMER
    // ═══════════════════════════════════════════════════════════════════════

    // Non-repeating timer: fires once per poll cycle. Fast when the binary is
    // available, slow when it is not (avoids spamming a missing binary).
    Timer {
        id: retryTimer
        interval: root.binaryAvailable
            ? Plasmoid.configuration.headsetControlPollingTime * 1000
            : 60000
        repeat: false
        onTriggered: root.refresh()
    }
}
