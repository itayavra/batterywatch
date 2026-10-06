import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils

// HID battery provider: reads devices not exposed via upower directly from hidraw
// Based on OpenRazerProvider.qml
// Author: TheDogORB <thedogorb@proton.me>
//
// Uses a small Python helper (bin/read_hid_devices) that matches known devices and returns JSON
// Requires access to /dev/hidraw*; devices found but not readable are reported
// as blocked so the widget can offer to copy the exact udev command for them.
Item {
    id: root
    visible: false

    // Helper binary, reads out hidraw, returns JSON with data
    readonly property string helperPath: Qt.resolvedUrl("../../bin/read_hid_devices").toString().slice(7)

    // Connection types
    readonly property int wirelessType: 1

    // Data passed to the applet
    property var devices: []

    // Holds the last parsed data while waiting for new ones
    property var pendingData: null
    readonly property var emptyList: []

    property bool hidEnabled: Plasmoid.configuration.enableHIDIntegration

    // Testing mode (reuses the "Debug mode" toggle in Advanced Settings):
    // no hardware needed, helper emits a fake device instead. With --simulate
    // the helper mirrors real behavior - it looks blocked until its udev rule
    // exists, then reports a battery.
    property bool debugMode: Plasmoid.configuration.debugMode

    onDebugModeChanged: {
        if (hidEnabled)
            refresh()
    }

    onHidEnabledChanged: {
        if (!hidEnabled) {
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

        // Parses data, number check is redundand but better to be safe than sorry
        const result = parsed
            .filter(d => typeof d.percentage === "number" || d.blocked === true)
            .map(d => ({
                name: d.name || i18n("Unknown Device"),
                serial: d.serial || d.name,
                percentage: d.percentage,
                charging: d.charging === true,
                blocked: d.blocked === true,
                vid: d.vid,
                pid: d.pid,
                unblockCommand: d.unblock_command,
                type: d.deviceType,
                icon: DeviceUtils.getIconForType(d.deviceType),
                connectionType: (typeof d.connectionType === "number") ? d.connectionType : wirelessType,
                source: "hid",
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

    // Refreshes on report every ~3-5s
    // When no device is present, retryTimer is used for periodic re-checks
    P5Support.DataSource {
        id: pollSource
        engine: "executable"
        connectedSources: []
        interval: 0

        onNewData: (src, data) => {
            disconnectSource(src)

            if (!root.hidEnabled) {
                root.devices = []
                return
            }

            if (!data.stdout || data["exit code"] !== 0) {
                if (root.devices.length > 0)
                    root.devices = []
                retryTimer.restart()
                return
            }

            try {
                const parsed = JSON.parse(data.stdout.trim())
                if (!Array.isArray(parsed)) {
                    if (root.devices.length > 0)
                        root.devices = []
                    retryTimer.restart()
                    return
                }
                root.pendingData = parsed
                Qt.callLater(root.updateDevices)
            } catch (e) {
                console.warn("BatteryWatch HID: Failed to parse helper output:", e)
                root.devices = []
            }
            retryTimer.restart()
        }

        Component.onCompleted: {
            if (root.hidEnabled)
                root.refresh()
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // POLLING TIMER
    // ═══════════════════════════════════════════════════════════════════════

    // Polls on a fixed interval (hidPollingTime, default 5s) whether devices
    // are present or not. The helper is stateless and re-reads every device on
    // each run, so a device that stops answering simply isn't reported and the
    // widget drops it on the next poll - no state to keep in sync.
    Timer {
        id: retryTimer
        interval: Plasmoid.configuration.hidPollingTime * 1000
        repeat: false
        onTriggered: root.refresh()
    }
}