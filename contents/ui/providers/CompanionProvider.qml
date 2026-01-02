import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import "../DeviceUtils.js" as DeviceUtils

// BatteryWatch Companion service provider
Item {
    id: root
    visible: false
    
    property var devices: []
    property bool available: false
    
    function refresh() {
        pollSource.connectSource("gdbus call --session --dest org.batterywatch.Companion --object-path /org/batterywatch/Companion --method org.batterywatch.Companion.GetDevices 2>/dev/null")
    }
    
    // Parse Companion JSON data into device object
    function parseCompanionDevice(data) {
        if (!data || typeof data !== 'object') return null
        
        var id = data.id || data.address || ""
        if (!id) return null
        
        var deviceType = data.device_type || "unknown"
        var icon = data.icon_name || DeviceUtils.getIconForType(deviceType)
        
        // Handle batteries array
        var batteries = []
        var percentage = 0
        
        if (Array.isArray(data.batteries) && data.batteries.length > 0) {
            var total = 0
            data.batteries.forEach(function(bat) {
                var pct = typeof bat.percentage === 'number' ? bat.percentage : 0
                var label = bat.label || null
                var labelLower = (label || "").toLowerCase()
                
                total += pct
                var isCharging = bat.charging === true
                batteries.push({
                    label: label,
                    percentage: pct,
                    charging: isCharging,
                    // Only show in tray if: not Case AND not charging
                    showInTray: labelLower !== "case" && !isCharging
                })
            })
            percentage = Math.round(total / batteries.length)
        } else if (typeof data.percentage === 'number') {
            percentage = data.percentage
        }
        
        return {
            name: data.name || data.model || "Unknown Device",
            serial: id,
            percentage: percentage,
            icon: icon,
            type: deviceType,
            batteries: batteries,
            model: data.model || "",
            source: "companion",
            nativePath: "",
            objectPath: "",
            connectionType: 2,
            bluetoothAddress: id
        }
    }
    
    P5Support.DataSource {
        id: pollSource
        engine: "executable"
        connectedSources: []
        interval: 0
        
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName)
            
            var output = data["stdout"] || ""
            if (data["exit code"] !== 0 || !output.trim()) {
                if (root.available) {
                    root.available = false
                    root.devices = []
                    console.log("BatteryWatch: Companion service disconnected")
                }
                return
            }
            
            // Parse gdbus output: ('json_string',)
            var match = output.match(/\('(.*)'\,?\)/)
            if (!match) return
            
            try {
                var jsonStr = match[1].replace(/\\'/g, "'").replace(/\\"/g, '"').replace(/\\\\/g, '\\')
                var rawDevices = JSON.parse(jsonStr)
                
                if (!Array.isArray(rawDevices)) return
                
                root.devices = rawDevices.map(function(d) {
                    return parseCompanionDevice(d)
                }).filter(function(d) { return d !== null })
                
                if (!root.available) {
                    root.available = true
                    console.log("BatteryWatch: Companion service connected")
                }
            } catch (e) {
                console.warn("BatteryWatch: Failed to parse companion data:", e)
            }
        }
    }
    
    // Poll frequently when service is available, probe slowly when not
    Timer {
        interval: root.available ? 10000 : 60000
        running: true
        repeat: true
        onTriggered: root.refresh()
    }
    
    Component.onCompleted: root.refresh()
}
