import QtQuick 2.15
import org.kde.bluezqt as BluezQt
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils

// BluezProvider: reads Bluetooth device battery levels directly from BlueZ
// via the org.kde.bluezqt QML module (BluezQt.Manager).
//
// Some Bluetooth devices (e.g. 8bitdo controllers :( )) expose battery info through
// the Bluetooth GATT Battery Service but NOT through UPower. The system
// Bluetooth menu reads this data from BlueZ directly.
//
// This provider is the fix for devices that show 0% in UPower-based providers
// but report correct battery in the Bluetooth settings panel.
//
// SOURCES / REFERENCES:
// - BluezQt QML API:     https://api.kde.org/frameworks/bluez-qt/html/
// - BluezQt Device.h      https://invent.kde.org/libraries/bluez-qt/-/blob/master/src/device.h
//   (enum values for type: Keyboard=8, Mouse=9, Joypad=10, Gamepad=11, etc.)
// - MBattery (approach):  https://github.com/MCC45TR/Plasma6Widgets/tree/main/battery
//   (uses the same BluezQt.Manager + dev.battery.percentage pattern)
// - UPowerProvider.qml:   same-directory reference for bluetoothctl disconnect pattern
// - KDEConnectProvider:   same-directory reference for config toggle + polling pattern
// - DeviceUtils.js:       same-directory reference for getIconForType()
// - main.qml:             mergeDevices() expects the device object shape defined here
Item {
    id: root
    visible: false

    // Exposed device list consumed by main.qml's mergeDevices()
    property var devices: []

    // Connection type constant matching the existing convention:
    // 0 = wired, 1 = wireless, 2 = bluetooth
    readonly property int bluetoothType: 2

    // Config toggle (default: true, set in main.xml under group "Bluez")
    property bool bluezEnabled: Plasmoid.configuration.enableBluezIntegration

    // Clear or populate devices when the toggle changes
    onBluezEnabledChanged: {
        if (!bluezEnabled) {
            devices = []
        } else {
            updateDevices()
        }
    }

    // BluezQt.Manager — the singleton that gives us access to all Bluetooth
    // devices known to BlueZ. Its .devices[] array contains all paired devices;
    // each has .connected, .battery (with .percentage), .name, .address, .type, etc.
    // Docs: https://api.kde.org/frameworks/bluez-qt/html/classBluezQt_1_1Manager.html
    property BluezQt.Manager btManager: BluezQt.Manager

    // Called externally by main.qml's refreshDevices()
    function refresh() {
        updateDevices()
    }

    // Core: iterate all BlueZ devices, pick connected ones that expose a
    // battery percentage >= 0, and build a device object for each.
    // The device object shape matches what main.qml's mergeDevices() expects
    // (see: main.qml -> fullRepresentation -> device properties used).
    function updateDevices() {
        if (!btManager.operational) {
            devices = []
            return
        }

        var newDevices = []
        for (var i = 0; i < btManager.devices.length; i++) {
            var dev = btManager.devices[i]
            if (dev.connected && dev.battery) {
                var per = dev.battery.percentage
                if (per >= 0) {
                    var deviceType = getDeviceType(dev)
                    newDevices.push({
                        name: dev.name,
                        serial: dev.address,              // Bluetooth MAC address — used for dedup in mergeDevices()
                        icon: DeviceUtils.getIconForType(deviceType),
                        percentage: per,
                        charging: false,                   // BlueZ doesn't expose charging state for BT devices
                        connectionType: bluetoothType,
                        source: "bluez",
                        bluetoothAddress: dev.address,
                        disconnect: makeDisconnect(dev.address),
                        disconnectTooltip: i18n("Disconnect Bluetooth device")
                    })
                }
            }
        }
        devices = newDevices
    }

    // Creates a disconnect closure that runs bluetoothctl with the device's MAC
    // Same approach as UPowerProvider.qml's disconnect for Bluetooth devices.
    function makeDisconnect(address) {
        return function() {
            disconnectSource.connectSource("bluetoothctl disconnect " + address)
        }
    }

    // Maps a BlueZ device to a DeviceUtils-compatible type string.
    // First tries name keyword matching (catches most devices regardless of
    // BlueZ classification), then falls back to the numeric BlueZ Device.Type enum.
    //
    // Name-matching approach inspired by MBattery's getBluetoothIcon().
    // Enum values from BluezQt Device.h:
    // https://invent.kde.org/libraries/bluez-qt/-/blob/master/src/device.h
    //   1=Phone, 3=Computer, 5=Headset, 6=Headphones, 8=Keyboard, 9=Mouse,
    //   10=Joypad, 11=Gamepad, 12=Tablet, 17=Display, 18=Wearable, 31=Smartphone,
    //   32=Laptop, 33=Watch
    function getDeviceType(dev) {
        var name = (dev.name || "").toLowerCase()

        if (name.indexOf("gamepad") !== -1 || name.indexOf("controller") !== -1 || name.indexOf("joy") !== -1 || name.indexOf("8bitdo") !== -1)
            return "gamepad"
        if (name.indexOf("mouse") !== -1 && name.indexOf("keyboard") === -1)
            return "mouse"
        if (name.indexOf("keyboard") !== -1 || name.indexOf("keypad") !== -1)
            return "keyboard"
        if (name.indexOf("headset") !== -1)
            return "headset"
        if (name.indexOf("headphone") !== -1 || name.indexOf("earphone") !== -1 || name.indexOf("earbud") !== -1)
            return "headphones"
        if (name.indexOf("speaker") !== -1)
            return "headphones"
        if (name.indexOf("phone") !== -1 || name.indexOf("mobile") !== -1)
            return "phone"
        if (name.indexOf("tablet") !== -1 || name.indexOf("ipad") !== -1)
            return "tablet"
        if (name.indexOf("watch") !== -1 || name.indexOf("band") !== -1)
            return "watch"
        if (name.indexOf("laptop") !== -1 || name.indexOf("notebook") !== -1)
            return "laptop"

        switch (dev.type) {
            case 8: return "keyboard"
            case 9: return "mouse"
            case 10: case 11: return "gamepad"
            case 12: return "tablet"
            case 1: case 31: return "phone"
            case 5: return "headset"
            case 6: return "headphones"
            case 18: case 33: return "watch"
            case 17: return "display"
            case 32: return "laptop"
            case 3: return "computer"
            default: return "gamepad"
        }
    }

    // Executable data source used to run bluetoothctl for disconnect.
    // Same pattern as UPowerProvider.qml's btDisconnectSource.
    P5Support.DataSource {
        id: disconnectSource
        engine: "executable"
        interval: 0
        onNewData: (src, data) => disconnectSource(src)
    }

    // React to BlueZ events in real time rather than only polling.
    // Same signal-binding pattern as MBattery's DeviceModel.qml.
    // BluezQt.Manager signals:
    // https://api.kde.org/frameworks/bluez-qt/html/classBluezQt_1_1Manager.html#signals
    Connections {
        target: btManager
        function onDeviceAdded() { updateDevices() }
        function onDeviceChanged() { updateDevices() }
        function onDeviceRemoved() { updateDevices() }
        function onOperationalChanged() { updateDevices() }
    }

    // Fallback polling timer in case BlueZ events are missed.
    // Same pattern as KDEConnectProvider.qml's polling Timer.
    // Interval is read from config (seconds), default 5s.
    Timer {
        interval: Plasmoid.configuration.bluezPollingTime * 1000
        running: true
        repeat: true
        onTriggered: updateDevices()
    }
}
