import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils

// HeadsetControl provider: reads battery from gaming headsets via the
// headsetcontrol CLI tool (https://github.com/Sapd/HeadsetControl).
// Covers SteelSeries, HyperX, Corsair, ROCCAT, Audeze, Sony and others.
//
// Requires headsetcontrol to be installed and accessible in PATH.
// Logitech devices (VID 0x046d) are skipped here because the HID provider
// already handles them with direct protocol support.
Item {
    id: root
    visible: false

    readonly property string binaryCmd: "headsetcontrol -o json"
    // Logitech vendor ID — skipped to avoid duplicating HID provider devices
    readonly property string logitechVid: "0x046d"

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
                // Skip Logitech — HID provider handles those
                if (d.id_vendor === logitechVid) return false
                const status = d.battery.status
                if (status !== "BATTERY_AVAILABLE" && status !== "BATTERY_CHARGING") return false
                // HeadsetControl may report level -1 while charging; skip those
                if (typeof d.battery.level !== "number" || d.battery.level < 0) return false
                return true
            })
            .map(d => ({
                name: d.device || i18n("Unknown Headset"),
                serial: "hc-" + d.id_vendor + ":" + d.id_product,
                percentage: d.battery.level,
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

            // Try parsing stdout first — headsetcontrol exits 1 with valid
            // JSON when no headsets are found (normal idle state).
            if (data.stdout && data.stdout.trim()) {
                try {
                    const parsed = JSON.parse(data.stdout.trim())
                    if (parsed && Array.isArray(parsed.devices)) {
                        root.pendingData = parsed.devices
                        if (!root.binaryAvailable) {
                            root.binaryAvailable = true
                            console.warn("BatteryWatch: headsetcontrol connected")
                        }
                        Qt.callLater(root.updateDevices)
                        retryTimer.restart()
                        return
                    }
                } catch (e) {
                    // Unparseable output — fall through to unavailable handling
                }
            }

            // No valid output — binary is missing or broken
            if (root.binaryAvailable) {
                root.binaryAvailable = false
                root.devices = []
                console.warn("BatteryWatch: headsetcontrol binary not found")
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
