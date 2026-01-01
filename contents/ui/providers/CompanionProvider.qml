import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import "CompanionProvider.js" as Logic

// Companion service provider - thin QML wrapper around JS logic
// This is OPTIONAL - the widget works without it
Item {
    id: provider
    visible: false
    
    // Output: list of devices from companion service
    property var devices: []
    property bool available: false
    
    function refresh() {
        pollSource.connectSource(pollCommand)
    }
    
    readonly property string pollCommand: "gdbus call --session --dest org.batterywatch.Companion --object-path /org/batterywatch/Companion --method org.batterywatch.Companion.GetDevices 2>/dev/null"
    
    P5Support.DataSource {
        id: pollSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName)
            
            var output = data["stdout"] || ""
            var exitCode = data["exit code"]
            
            if (exitCode === 0 && output.trim().length > 0) {
                var parsed = Logic.parseAllDevices(output)
                if (parsed !== null) {
                    provider.devices = parsed
                    if (!provider.available) {
                        provider.available = true
                        console.log("BatteryWatch: Companion service connected")
                    }
                }
            } else {
                if (provider.available) {
                    provider.available = false
                    provider.devices = []
                    console.log("BatteryWatch: Companion service not available")
                }
            }
        }
    }
    
    // Poll every 10s
    Timer {
        interval: 10000
        running: true
        repeat: true
        onTriggered: provider.refresh()
    }
    
    // Initial poll after 2s
    Timer {
        interval: 2000
        running: true
        repeat: false
        onTriggered: provider.refresh()
    }
}
