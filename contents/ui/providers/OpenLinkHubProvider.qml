import QtQuick 2.15
import org.kde.plasma.plasma5support 2.0 as P5Support
import org.kde.plasma.plasmoid 2.0
import "../DeviceUtils.js" as DeviceUtils

// OpenLinkHub device provider v 1.1.0
//		  (\_/)
//		 =('.')=
//		/|" ‾ "|\
//		 |_____|
// 	~AzzyBunn was here


//		  |\_/|
//		 /     \
//		/_.~ ~,_\   -Keely
//		   \@/    
// & lisekilis was here to fix shit up

Item {
	id: root
	visible: false
	
	property var devices: []
	property bool available: false
	property bool debugMode: false

	property int port: Plasmoid.configuration.openLinkHubApiPort
	
	property var deviceTypes: [
		"keyboard",
		"mouse",
		"headset"
	]

	function refresh() {
		if(!plasmoid.configuration.enableOpenLinkHubIntegration){return}
		fetchBatteryData()
		if(debugMode) print("Devices found:", devices.length)
	}

	// Step 1: Send a HTML request to localhost:[port] asking about battery information
	function fetchBatteryData(){
		var req = new XMLHttpRequest();
		
		// Step 1.1: Filter HTTP ready states and responses
		req.onreadystatechange = () => {
			if (req.readyState !== XMLHttpRequest.DONE) return;
			
			if (req.status !== 200) {
				available = false;
				if(debugMode) console.log("Server error:", req.status);
				return;
			}
			
			try {
				const response = JSON.parse(req.responseText); // Step 1.2: Parse the HTTP response
				const batteryData = response.data;
				if(!batteryData){
					console.log("Server responded without any battery data!");
					available = false;
					return;
				}
				available = true; //Server responded with data about battery -> service available
				processBatteryData(batteryData); // Battery data -> Step 2
			} catch (e) {
				console.error("Failed to parse battery data:", e);
				available = false;
			}
		}

		// Step 1.3: Send request
		req.open("GET", "http://127.0.0.1:"+port+"/api/batteryStats");
		req.send();
	}

	// Step 2: Process the received battery data
	function processBatteryData(data){
		// Add null/undefined check for data
		if (!data || typeof data !== 'object') {
			if(debugMode) console.log("Invalid battery data received:", data);
			devices = []; // Clear devices if no valid data
			return;
		}
		
		let batteryDevices = [];
		try {
			Object.keys(data).forEach((serial) => {
				const device = data[serial];
				// Check if device data is valid before processing
				if (!device || typeof device !== 'object') {
					if(debugMode) console.log("Invalid device data for serial:", serial);
					return; // Skip this device
				}
				  
				batteryDevices.push({
					serial: serial,
					name: device.Device || "Unknown Device",
					percentage: device.Level || 0,
					deviceType: device.DeviceType || 0,
					type: deviceTypes[device.DeviceType] || "unknown"
				});
			});
		} catch (e) {
			console.error("Error processing battery data:", e);
			return;
		}
		
		let oldDevices = devices.slice(); // Copy current devices to check for updates
		let updatedSerials = [];

		batteryDevices.forEach((batteryDevice) => {
			// Add safety check for batteryDevice
			if (!batteryDevice || !batteryDevice.serial) {
				if(debugMode) console.log("Invalid battery device data, skipping");
				return;
			}
			
			var existingDeviceIndex = devices.findIndex(d => d && d.serial === batteryDevice.serial);
			if (existingDeviceIndex >= 0) {
				// Device already exists, update its battery percentage
				fetchDevice(batteryDevice.serial, batteryDevice, (deviceData) => {
					if (deviceData && !isDeviceConnected(deviceData)) {
						if (debugMode) console.log("Device " + batteryDevice.serial + " is not connected, removing.");
						devices = devices.filter(d => d && d.serial !== batteryDevice.serial);
						return;						
					}
				});
				// Ensure the device still exists before updating
				if (devices[existingDeviceIndex]) {
					devices[existingDeviceIndex].percentage = batteryDevice.percentage;
				}
				updatedSerials.push(batteryDevice.serial);
			} else {
				// New device, fetch its full data
				fetchDevice(batteryDevice.serial, batteryDevice, (deviceData) => {
					if (deviceData) {
						var newDevice = createDeviceObject(deviceData, batteryDevice);
						if (newDevice) {
							devices.push(newDevice);
						}
					}
				});
			}
		});
		
		// Remove devices that are no longer present, with null checks
		devices = devices.filter(d => d && d.serial && (updatedSerials.includes(d.serial) || batteryDevices.some(bd => bd && bd.serial === d.serial)));

		if(debugMode) console.log("Processed devices:", JSON.stringify(devices, null, 2));
	}

	function createDeviceObject(data, batteryDevice) {
		// Add safety checks for null/undefined data
		if (!data || typeof data !== 'object') {
			if (debugMode) console.log("Invalid device data received for device creation");
			return null;
		}
		
		if (!batteryDevice || !batteryDevice.serial) {
			if (debugMode) console.log("Invalid battery device data for device creation");
			return null;
		}
		
		if (!data.Connected) {
			if (debugMode) console.log("Device " + batteryDevice.serial + " is not connected, skipping.");
			return null;
		}
		return {
			name: data.product || batteryDevice.name || "Unknown Device",
			serial: data.serial || batteryDevice.serial,
			percentage: batteryDevice.percentage || 0,
			type: batteryDevice.type || "unknown",
			icon: DeviceUtils.getIconForType(batteryDevice.type || "unknown"),
			source: "openlinkhub",
			connectionType: 2, // Always wireless if passed to the device list
			model: null,
			objectPath: null,
			nativePath: null,
			bluetoothAddress: null,
			batteries: [],
		};
	}
	
	function fetchDevice(serial, batteryDevice, callback) {
		if (debugMode) console.log("Fetching device data for serial: " + serial);
		
		let req = new XMLHttpRequest();
		req.onreadystatechange = () => {
			if (req.readyState === XMLHttpRequest.DONE) {
				if (req.status === 200) {
					try {
						let response = JSON.parse(req.responseText);
						if (debugMode) console.log("Successfully fetched device data for serial: " + serial);
						callback(response.device || null);
					} catch (e) {
						console.error("Failed to parse device data:", e);
						callback(null);
					}
				} else {
					console.error("Server error fetching device " + serial + ":", req.status);
					callback(null);
				}
			}
		};
		
		req.open("GET", "http://127.0.0.1:" + port + "/api/devices/" + serial);
		req.send();
	}

	// Device connection check - can be used to filter devices
	function isDeviceConnected(deviceData) {
		// If the device is missing the 'Connected' field it probably means it's wired
		// Some devices stop supplying 'Connected' field when connected via USB
		return deviceData.Connected !== false;
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

// The most idiotic thing about JS.
// You can't copy objects normally.
// It made me stay up for hours.
// Why can't there be something like Lua's table.deepcopy()
// I just wanted an identical object that's not linked.
// Why didn't JSON.parse(JSON.stringify(currentDevices)); work
// I hate it here.
//
//		  (\_/)
//		 =(x.x)=
//		/|‾‾‾‾‾|\
//		 |_____|
// 	~AzzyBunn
//
// -- in memory of AzzyBunn's sanity
//