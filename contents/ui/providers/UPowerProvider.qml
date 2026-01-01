import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import "UPowerProvider.js" as Logic

// UPower device provider - thin QML wrapper around JS logic
Item {
    id: provider
    visible: false
    
    // Output: list of devices from UPower
    property var devices: []
    
    function refresh() {
        listSource.connectSource("upower -e")
    }
    
    // Fetch device list
    P5Support.DataSource {
        id: listSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName)
            
            var result = Logic.parseDeviceList(data["stdout"], provider.devices)
            
            // Fetch details for new devices
            for (var i = 0; i < result.newPaths.length; i++) {
                detailsSource.connectSource("upower -i " + result.newPaths[i])
            }
            
            // Remove disconnected devices
            var filtered = Logic.filterDisconnectedDevices(provider.devices, result.foundPaths)
            if (filtered.length !== provider.devices.length) {
                provider.devices = filtered
            }
        }
        
        Component.onCompleted: connectSource("upower -e")
    }
    
    // Fetch device details
    P5Support.DataSource {
        id: detailsSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName)
            
            var parts = sourceName.split(" ")
            var objectPath = parts[parts.length - 1]
            
            var deviceInfo = Logic.parseDeviceDetails(data["stdout"], objectPath)
            if (deviceInfo) {
                provider.devices = Logic.updateDeviceInList(provider.devices, deviceInfo)
            }
        }
    }
    
    // Check for device changes every 2s
    Timer {
        interval: 2000
        running: true
        repeat: true
        onTriggered: listSource.connectSource("upower -e")
    }
    
    // Refresh battery levels every 60s
    Timer {
        interval: 60000
        running: true
        repeat: true
        onTriggered: {
            for (var i = 0; i < provider.devices.length; i++) {
                if (provider.devices[i].objectPath) {
                    detailsSource.connectSource("upower -i " + provider.devices[i].objectPath)
                }
            }
        }
    }
}
