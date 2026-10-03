import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils

// Solaar battery provider: Logitech (and Lenovo receiver) HID++ devices via
// Solaar's own library. Based on HIDDevicesProvider.qml.
//
// Uses a small Python helper (bin/read_solaar_devices) that talks to Solaar's
// logitech_receiver module and returns the same JSON schema as read_hid_devices.
// Requires Solaar (distro package, pip or pipx); when the library is missing
// the helper reports {"error": "solaar-missing", ...} and the provider stays
// empty with a console note - the widget simply has no Solaar devices then.
Item {
    id: root
    visible: false

    // Helper binary, enumerates through Solaar and returns JSON with data
    readonly property string helperPath: Qt.resolvedUrl("../../bin/read_solaar_devices").toString().slice(7)

    // Connection types (same identifiers as the other providers)
    readonly property int wirelessType: 1
    readonly property int bluetoothType: 2

    // Data passed to the applet
    property var devices: []

    // Holds the last parsed data while waiting for new ones
    property var pendingData: null
    readonly property var emptyList: []

    // True while the helper reports the Solaar library unavailable; logged once
    property bool solaarUnavailable: false

    // Poll-interval multiplier while the helper cannot produce data (Solaar
    // missing, helper broken): most users don't have Solaar, so a failed run
    // backs off to one check per minute instead of spawning it every interval.
    // Reset on the first successful run, so installing Solaar is picked up.
    property int failureBackoff: 1

    property bool solaarEnabled: Plasmoid.configuration.enableSolaarIntegration

    // Testing mode (reuses the "Debug mode" toggle in Advanced Settings):
    // no hardware needed, helper emits fake devices instead.
    property bool debugMode: Plasmoid.configuration.debugMode

    onDebugModeChanged: {
        if (solaarEnabled)
            refresh()
    }

    onSolaarEnabledChanged: {
        if (!solaarEnabled) {
            devices = []
            pendingData = null
            retryTimer.stop()
        } else {
            failureBackoff = 1
            refresh()
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // GUI RELATED FUNCTIONS
    // ═══════════════════════════════════════════════════════════════════════

    // Refresh via "refresh" button in the GUI
    function refresh() {
        pollSource.disconnectSource(helperPath)
        pollSource.connectSource(debugMode ? helperPath + " --simulate" : helperPath)
    }

    // ═══════════════════════════════════════════════════════════════════════
    // HELPER FUNCTIONS
    // ═══════════════════════════════════════════════════════════════════════

    // Rebuilds the devices list from pendingData and updates the applet
    // Happens only if something actually changed -> skips unnecessary UI redraws
    function updateDevices() {
        const parsed = root.pendingData
        if (!parsed) return

        // Parses data; number check is redundant but better to be safe than sorry
        const result = parsed
            .filter(d => typeof d.percentage === "number" || d.blocked === true)
            .map(d => {
                const device = {
                    name: d.name || i18n("Unknown Device"),
                    serial: d.serial || d.name,
                    percentage: d.percentage,
                    charging: d.charging === true,
                    blocked: d.blocked === true,
                    unblockCommand: d.unblock_command,
                    type: d.deviceType,
                    icon: DeviceUtils.getIconForType(d.deviceType || "unknown"),
                    connectionType: (typeof d.connectionType === "number") ? d.connectionType : wirelessType,
                    source: "solaar",
                    batteries: emptyList,
                }

                // Show disconnect button for Bluetooth connections
                if (device.connectionType === bluetoothType && d.bluetooth_address) {
                    const addr = String(d.bluetooth_address).replace(/[_\-]/g, ":").toUpperCase()
                    device.disconnect = () => btDisconnectSource.connectSource("bluetoothctl disconnect " + addr)
                    device.disconnectTooltip = i18n("Disconnect device")
                }
                return device
            })

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

    // One-shot disconnect for Bluetooth devices
    P5Support.DataSource {
        id: btDisconnectSource
        engine: "executable"
        interval: 0
        onNewData: (src, data) => disconnectSource(src)
    }

    // Refreshes on report every polling interval; retryTimer re-checks
    P5Support.DataSource {
        id: pollSource
        engine: "executable"
        connectedSources: []
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src)

            if (!root.solaarEnabled) {
                root.devices = []
                root.pendingData = null
                return
            }

            // The helper communicates "Solaar unusable" as a JSON error object
            // on a zero exit; anything else (crash, empty output) is treated
            // the same: no devices, logged once, backed-off polling. Devices
            // are cleared like the HID provider does - stateless, no stale
            // entries kept across failed runs.
            try {
                const parsed = JSON.parse(data.stdout.trim())
                if (Array.isArray(parsed)) {
                    root.solaarUnavailable = false
                    root.failureBackoff = 1
                    root.pendingData = parsed
                    Qt.callLater(root.updateDevices)
                } else if (parsed && parsed.error) {
                    if (!root.solaarUnavailable) {
                        root.solaarUnavailable = true
                        // i18n: %1 is the helper's hint why Solaar is unusable.
                        console.log(i18n("BatteryWatch: Solaar library unavailable (%1)", parsed.hint || parsed.error))
                    }
                    root.failureBackoff = 6
                    root.devices = []
                    root.pendingData = []
                } else {
                    throw new Error("expected an array")
                }
            } catch (e) {
                if (!root.solaarUnavailable) {
                    root.solaarUnavailable = true
                    root.failureBackoff = 6
                    console.warn("BatteryWatch Solaar: Failed to parse helper output:", e)
                }
                root.devices = []
                root.pendingData = []
            }
            retryTimer.restart()
        }

        Component.onCompleted: {
            if (root.solaarEnabled)
                root.refresh()
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // POLLING TIMER
    // ═══════════════════════════════════════════════════════════════════════

    // Polls on a fixed interval whether devices are present or not. The
    // helper is stateless and re-reads every device on each run, so a device
    // that stops answering (asleep mouse, removed pairing) simply isn't
    // reported and the widget drops it on the next poll - no state to sync.
    Timer {
        id: retryTimer
        interval: Plasmoid.configuration.solaarPollingTime * 1000 * root.failureBackoff
        repeat: false
        onTriggered: root.refresh()
    }
}
