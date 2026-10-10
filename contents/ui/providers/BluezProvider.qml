import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0

// BlueZ device provider.
//
// Some Bluetooth devices (e.g. 8bitdo controllers :( )) expose battery info through
// the Bluetooth GATT Battery Service but NOT through UPower. The system
// Bluetooth menu reads this data from BlueZ directly.
//
// This provider is the fix for devices that show 0% in UPower-based providers
// but report correct battery in the Bluetooth settings panel.
//
Item {
    id: root
    visible: false

    property var devices: []

    // 0 = wired, 1 = wireless, 2 = bluetooth
    readonly property int bluetoothType: 2

    property bool bluezEnabled: Plasmoid.configuration.enableBluezIntegration

    function refresh() {
        if (!root.bluezEnabled)
            return
        listSource.connectSource("bluetoothctl devices Connected")
        root.devices.forEach(d => {
            detailsSource.disconnectSource("bluetoothctl info " + d.serial)
            detailsSource.connectSource("bluetoothctl info " + d.serial)
        })
    }

    onBluezEnabledChanged: {
        if (root.bluezEnabled) {
            root.refresh()
            return
        }
        listSource.disconnectSource("bluetoothctl devices Connected")
        root.devices.forEach(d =>
            detailsSource.disconnectSource("bluetoothctl info " + d.serial))
        root.devices = []
    }

    // Parse `bluetoothctl info <address>` output; null when the device is not
    // connected or reports no battery through the GATT Battery Service.
    function parseBluezInfo(output, address) {
        var name = ""
        var connected = false
        var percentage = -1
        var bluezIcon = ""

        var lines = output.split("\n")
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim()
            if (line.indexOf("Name:") !== -1) {
                name = line.split(":").slice(1).join(":").trim()
            } else if (line.indexOf("Connected:") !== -1) {
                connected = line.split(":")[1].trim() === "yes"
            } else if (line.indexOf("Battery Percentage:") !== -1) {
                // "Battery Percentage: 0x50 (80)"; some bluez prints just the decimal
                var m = line.match(/\((\d+)\)/) || line.match(/Battery Percentage:\s*(\d+)%?$/)
                if (m)
                    percentage = parseInt(m[1])
            } else if (line.indexOf("Icon:") !== -1) {
                bluezIcon = line.split(":").slice(1).join(":").trim()
            }
        }

        if (!connected || percentage < 0)
            return null

        return {
            name: name || address,
            // Bluetooth MAC address - used for dedup in main.qml's mergeDevices()
            serial: address,
            // BlueZ icon names are icon-spec names already; pass them through
            icon: bluezIcon || "battery-symbolic",
            percentage: percentage,
            // The GATT Battery Service has no charging flag; null leaves it
            // unknown so mergeDevices() can fill it from another provider
            charging: null,
            connectionType: bluetoothType,
            source: "bluez",
            bluetoothAddress: address,
            disconnect: () => btDisconnectSource.connectSource("bluetoothctl disconnect " + address),
            disconnectTooltip: i18n("Disconnect device")
        }
    }

    P5Support.DataSource {
        id: btDisconnectSource
        engine: "executable"
        interval: 0
        onNewData: (src, data) => disconnectSource(src)
    }

    P5Support.DataSource {
        id: listSource
        engine: "executable"
        connectedSources: []
        interval: 0

        onNewData: (sourceName, data) => {
            disconnectSource(sourceName)
            if (!root.bluezEnabled) {
                root.devices = []
                return
            }

            // "Device AC:36:1B:D9:FC:38 DualSense Wireless Controller"
            var lines = data["stdout"].split("\n")
            var found = []

            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim()
                if (line.indexOf("Device ") !== 0)
                    continue
                var address = line.split(" ")[1]
                if (!address)
                    continue
                found.push(address)

                // Fetch details for unknown devices
                if (!root.devices.some(d => d.serial === address))
                    detailsSource.connectSource("bluetoothctl info " + address)
            }

            // Remove disconnected devices and their detail sources
            var filtered = root.devices.filter(d => found.indexOf(d.serial) !== -1)
            if (filtered.length !== root.devices.length) {
                root.devices.forEach(d => {
                    if (found.indexOf(d.serial) === -1)
                        detailsSource.disconnectSource("bluetoothctl info " + d.serial)
                })
                root.devices = filtered
            }
        }

        Component.onCompleted: if (root.bluezEnabled) connectSource("bluetoothctl devices Connected")
    }

    P5Support.DataSource {
        id: detailsSource
        engine: "executable"
        connectedSources: []
        interval: Plasmoid.configuration.bluezPollingTime * 1000

        onNewData: (sourceName, data) => {
            if (!root.bluezEnabled) {
                root.devices = []
                return
            }
            var address = sourceName.split(" ").pop()
            var info = parseBluezInfo(data["stdout"], address)

            // Not connected, or no battery reported: nothing to show either way
            if (info === null) {
                var without = root.devices.filter(d => d.serial !== address)
                if (without.length !== root.devices.length) {
                    root.devices = without.sort((a, b) => (a.name || "").localeCompare(b.name || ""))
                }
                return
            }

            // Update or add device
            var updated = false
            var newDevices = root.devices.map(d => {
                if (d.serial === address) {
                    updated = true
                    return info
                }
                return d
            })

            if (!updated) {
                newDevices.push(info)
            }

            root.devices = newDevices.sort((a, b) => (a.name || "").localeCompare(b.name || ""))
        }
    }

    // Re-list connected devices so new ones get a detail source; the detail
    // sources poll each device on their own interval
    Timer {
        interval: Plasmoid.configuration.bluezPollingTime * 1000
        running: root.bluezEnabled
        repeat: true
        onTriggered: listSource.connectSource("bluetoothctl devices Connected")
    }
}
