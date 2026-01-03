import QtQuick 2.15
import QtQuick.Layouts
import org.kde.plasma.plasmoid 2.0
import org.kde.plasma.components 3.0 as PlasmaComponents
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami 2.20 as Kirigami
import org.kde.plasma.plasma5support 2.0 as P5Support
import "providers"

PlasmoidItem {
	id: root

	// ═══════════════════════════════════════════════════════════════════════
	// PROVIDERS
	// ═══════════════════════════════════════════════════════════════════════

	UPowerProvider {
		id: upowerProvider
	}

	CompanionProvider {
		id: companionProvider
	}

	OpenLinkHubProvider {
		id: openLinkHubProvider
	}

	// List of providers (in priority order)
	property var providers: [upowerProvider, companionProvider, openLinkHubProvider]

	// ═══════════════════════════════════════════════════════════════════════
	// DEVICE STATE
	// ═══════════════════════════════════════════════════════════════════════

	// Merged devices from all providers
	property var allDevices: mergeDevices(providers.map(p => p.devices))
	property var hiddenDevices: []

	property int visibleDeviceCount: {
		var count = 0
		for (var i = 0; i < allDevices.length; i++) {
			if (hiddenDevices.indexOf(allDevices[i].serial) === -1) {
				count++
			}
		}
		return count
	}

	property bool hasVisibleDevices: visibleDeviceCount > 0
	property bool hasAnyDevices: allDevices.length > 0
	property bool allDevicesHidden: hasAnyDevices && !hasVisibleDevices

	// Tray items: flattened list for compact representation
	// For multi-battery devices, only shows batteries with showInTray=true
	property var trayItems: buildTrayItems(allDevices, hiddenDevices)

	function buildTrayItems(devices, hidden) {
		var items = []
		for (var i = 0; i < devices.length; i++) {
			var device = devices[i]
			if (hidden.indexOf(device.serial) !== -1) continue

			// Multi-battery device (e.g., AirPods)
			if (device.batteries && device.batteries.length > 1) {
				for (var j = 0; j < device.batteries.length; j++) {
					var bat = device.batteries[j]

					// Skip batteries marked as not for tray (e.g., Case)
					if (bat.showInTray === false) continue

					items.push({
						icon: device.icon,
						percentage: bat.percentage,
						label: bat.label,
						deviceSerial: device.serial
					})
				}
			} else {
				// Single battery device
				items.push({
					icon: device.icon,
					percentage: device.percentage,
					label: null,
					deviceSerial: device.serial
				})
			}
		}
		return items
	}

	// ═══════════════════════════════════════════════════════════════════════
	// DEVICE MERGING
	// ═══════════════════════════════════════════════════════════════════════

	// Merge devices from multiple providers, avoiding duplicates
	// deviceProviders: array of device arrays in priority order (first = highest priority)
	function mergeDevices(deviceProviders) {
		var merged = []
		var seenIds = {}

		for (var providerIdx = 0; providerIdx < deviceProviders.length; providerIdx++) {
			var devices = deviceProviders[providerIdx]

			for (var i = 0; i < devices.length; i++) {
				var device = devices[i]
				var id = device.serial || device.objectPath || ""

				if (id && !seenIds[id]) {
					merged.push(device)
					seenIds[id] = true
				}
			}
		}

		// Sort by name
		merged.sort((a, b) => {
			var nameA = a.name || ""
			var nameB = b.name || ""
			return nameA.localeCompare(nameB)
		})

		return merged
	}

	// ═══════════════════════════════════════════════════════════════════════
	// WIDGET CONFIGURATION
	// ═══════════════════════════════════════════════════════════════════════

	preferredRepresentation: compactRepresentation

	toolTipMainText: i18n("BatteryWatch v%1", Plasmoid.metaData.version)
	toolTipSubText: {
		if (allDevices.length === 0) {
			return i18n("No connected devices")
		}

		var lines = []
		for (var i = 0; i < allDevices.length; i++) {
			var device = allDevices[i]
			if (hiddenDevices.indexOf(device.serial) !== -1) continue

			var line = device.name

			// Multi-battery display
			if (device.batteries && device.batteries.length > 1) {
				var parts = []
				for (var j = 0; j < device.batteries.length; j++) {
					var bat = device.batteries[j]
					parts.push(i18n("%1: %2%", bat.label || "Battery", bat.percentage))
				}
				line = i18n("%1 - %2", line, parts.join(i18n(", ")))
			} else {
				line = i18n("%1: %2%", line, device.percentage)
			}

			lines.push(line)
		}

		return lines.length > 0 ? lines.join("\n") : i18n("All devices hidden")
	}

	Plasmoid.status: {
		if (Plasmoid.userConfiguring) {
			return PlasmaCore.Types.ActiveStatus
		}
		if (Plasmoid.containment && Plasmoid.containment.corona && Plasmoid.containment.corona.editMode) {
			return PlasmaCore.Types.ActiveStatus
		}
		return hasAnyDevices ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.HiddenStatus
	}

	// ═══════════════════════════════════════════════════════════════════════
	// HIDDEN DEVICES PERSISTENCE
	// ═══════════════════════════════════════════════════════════════════════

	Component.onCompleted: {
		loadHiddenDevices()
	}

	function loadHiddenDevices() {
		var saved = Plasmoid.configuration.hiddenDevices
		if (saved) {
			hiddenDevices = saved.split(",").filter(s => s.length > 0)
		} else {
			hiddenDevices = []
		}
	}

	function saveHiddenDevices() {
		Plasmoid.configuration.hiddenDevices = hiddenDevices.join(i18n(", "))
	}

	function toggleDeviceVisibility(serial) {
		var index = hiddenDevices.indexOf(serial)
		if (index === -1) {
			hiddenDevices.push(serial)
		} else {
			hiddenDevices.splice(index, 1)
		}
		hiddenDevices = hiddenDevices.slice()
		saveHiddenDevices()
	}

	// ═══════════════════════════════════════════════════════════════════════
	// DEVICE ACTIONS
	// ═══════════════════════════════════════════════════════════════════════

	function refreshDevices() {
		for (var i = 0; i < providers.length; i++) {
			providers[i].refresh()
		}
	}

	P5Support.DataSource {
		id: bluetoothCtlSource
		engine: "executable"
		connectedSources: []
		interval: 0

		onNewData: (sourceName, data) => {
			disconnectSource(sourceName)
			Qt.callLater(refreshDevices)
		}
	}

	function disconnectBluetoothDevice(bluetoothAddress) {
		if (bluetoothAddress) {
			bluetoothCtlSource.connectSource("bluetoothctl disconnect " + bluetoothAddress)
		}
	}

	// ═══════════════════════════════════════════════════════════════════════
	// COMPACT REPRESENTATION (System Tray)
	// ═══════════════════════════════════════════════════════════════════════

	compactRepresentation: Item {
		property bool inEditMode: {
			if (Plasmoid.userConfiguring) return true
			if (Plasmoid.containment && Plasmoid.containment.corona && Plasmoid.containment.corona.editMode) return true
			return false
		}

		property bool shouldShow: root.hasVisibleDevices || root.allDevicesHidden || inEditMode

		Layout.minimumWidth: shouldShow ? -1 : 0
		Layout.minimumHeight: shouldShow ? -1 : 0
		Layout.preferredWidth: shouldShow ? (root.hasVisibleDevices ? row.implicitWidth : placeholderIcon.width) : 0
		Layout.preferredHeight: shouldShow ? (root.hasVisibleDevices ? row.implicitHeight : placeholderIcon.height) : 0
		Layout.maximumWidth: shouldShow ? -1 : 0
		Layout.maximumHeight: shouldShow ? -1 : 0

		Kirigami.Icon {
			id: placeholderIcon
			anchors.centerIn: parent
			source: root.allDevicesHidden ? Qt.resolvedUrl("../icons/hidden-devices.png") : Qt.resolvedUrl("../icons/battery-monitor.png")
			width: Kirigami.Units.iconSizes.smallMedium
			height: Kirigami.Units.iconSizes.smallMedium
			visible: !root.hasVisibleDevices && (inEditMode || root.allDevicesHidden)
		}

		RowLayout {
			id: row
			anchors.fill: parent
			spacing: Kirigami.Units.smallSpacing
			visible: root.hasVisibleDevices

			Repeater {
				model: root.trayItems

				RowLayout {
					spacing: 2

					Kirigami.Icon {
						source: modelData.icon
						Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
						Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
					}

					PlasmaComponents.Label {
						text: i18n("%1%", modelData.percentage)
						font.pixelSize: Kirigami.Theme.smallFont.pixelSize
					}
				}
			}
		}

		MouseArea {
			anchors.fill: parent
			onClicked: root.expanded = !root.expanded
		}
	}

	// ═══════════════════════════════════════════════════════════════════════
	// FULL REPRESENTATION (Popup)
	// ═══════════════════════════════════════════════════════════════════════

	fullRepresentation: Item {
		Layout.minimumWidth: Kirigami.Units.gridUnit * 25
		Layout.preferredWidth: Kirigami.Units.gridUnit * 30
		Layout.minimumHeight: Kirigami.Units.gridUnit * 8
		Layout.preferredHeight: {
			var baseHeight = Kirigami.Units.gridUnit * 5
			var deviceHeight = root.allDevices.length * Kirigami.Units.gridUnit * 4
			var totalHeight = baseHeight + deviceHeight
			var maxHeight = Kirigami.Units.gridUnit * 17
			return Math.min(totalHeight, maxHeight)
		}
		Layout.maximumHeight: Kirigami.Units.gridUnit * 35

		ColumnLayout {
			anchors.fill: parent
			anchors.margins: Kirigami.Units.largeSpacing
			spacing: Kirigami.Units.smallSpacing

			RowLayout {
				Layout.fillWidth: true
				spacing: Kirigami.Units.smallSpacing

				PlasmaComponents.Label {
					text: i18n("Device Battery Levels")
					font.bold: true
					font.pixelSize: Kirigami.Theme.defaultFont.pixelSize * 1.2
					Layout.fillWidth: true
				}

				PlasmaComponents.ToolButton {
					icon.name: "view-refresh"
					text: i18n("Refresh")
					display: PlasmaComponents.AbstractButton.IconOnly

					PlasmaComponents.ToolTip {
						text: i18n("Refresh devices")
					}

					onClicked: {
						refreshDevices()
					}
				}
			}

			PlasmaComponents.ScrollView {
				Layout.fillWidth: true
				Layout.fillHeight: true

				clip: true

				PlasmaComponents.ScrollBar.horizontal.policy: PlasmaComponents.ScrollBar.AlwaysOff

				ColumnLayout {
					width: parent.parent.width - Kirigami.Units.largeSpacing
					spacing: 0

					Repeater {
						model: root.allDevices

						ColumnLayout {
							Layout.fillWidth: true
							spacing: 0

							// Store reference to device for nested components
							property var device: modelData
							property bool hasMultipleBatteries: device.batteries && device.batteries.length > 1

							Item {
								Layout.fillWidth: true
								Layout.preferredHeight: Kirigami.Units.gridUnit * 4
								Layout.topMargin: Kirigami.Units.smallSpacing
								Layout.bottomMargin: Kirigami.Units.smallSpacing

								RowLayout {
									anchors.fill: parent
									spacing: Kirigami.Units.smallSpacing

									Kirigami.Icon {
										source: device.icon
										Layout.preferredWidth: Kirigami.Units.iconSizes.medium
										Layout.preferredHeight: Kirigami.Units.iconSizes.medium
										Layout.alignment: Qt.AlignVCenter
									}

									ColumnLayout {
										Layout.fillWidth: true
										Layout.alignment: Qt.AlignVCenter
										spacing: 2

										PlasmaComponents.Label {
											text: device.name || i18n("Unknown Device")
											font.bold: true
											Layout.fillWidth: true
											elide: Text.ElideRight
										}

										PlasmaComponents.Label {
											text: device.serial
											font.pixelSize: Kirigami.Theme.smallFont.pixelSize
											color: Kirigami.Theme.disabledTextColor
											Layout.fillWidth: true
											elide: Text.ElideRight
										}

										// Multi-battery row (shown under MAC address)
										RowLayout {
											visible: hasMultipleBatteries
											Layout.fillWidth: true
											spacing: Kirigami.Units.largeSpacing

											Repeater {
												model: hasMultipleBatteries ? device.batteries : []

												PlasmaComponents.Label {
													text: {
														var bat = modelData
														var label = bat.label || i18n("Battery")
														var charging = bat.charging ? " ⚡" : ""
														return i18n("%1: %2%%3", label, bat.percentage, charging)
													}
													font.pixelSize: Kirigami.Theme.smallFont.pixelSize
												}
											}
										}
									}

									RowLayout {
										Layout.alignment: Qt.AlignVCenter

										PlasmaComponents.ToolButton {
											visible: device.connectionType === 2 && device.bluetoothAddress
											icon.name: "network-disconnect"
											text: i18n("Disconnect")
											display: PlasmaComponents.AbstractButton.IconOnly
											onClicked: disconnectBluetoothDevice(device.bluetoothAddress)

											PlasmaComponents.ToolTip {
												text: i18n("Disconnect device")
											}

											MouseArea {
												anchors.fill: parent
												hoverEnabled: true
												cursorShape: Qt.PointingHandCursor
												onPressed: mouse.accepted = false
											}
										}

										PlasmaComponents.ToolButton {
											icon.name: root.hiddenDevices.indexOf(device.serial) === -1 ? "view-visible" : "view-hidden"
											text: root.hiddenDevices.indexOf(device.serial) === -1 ? i18n("Hide") : i18n("Show")
											display: PlasmaComponents.AbstractButton.IconOnly
											onClicked: toggleDeviceVisibility(device.serial)

											PlasmaComponents.ToolTip {
												text: root.hiddenDevices.indexOf(device.serial) === -1 ? i18n("Hide from tray") : i18n("Show in tray")
											}

											MouseArea {
												anchors.fill: parent
												hoverEnabled: true
												cursorShape: Qt.PointingHandCursor
												onPressed: mouse.accepted = false
											}
										}

										// Single battery: show percentage
										PlasmaComponents.Label {
											visible: !hasMultipleBatteries
											text: i18n("%1%", device.percentage)
											font.bold: true
											Layout.minimumWidth: Kirigami.Units.gridUnit * 2
											horizontalAlignment: Text.AlignRight
										}
									}
								}
							}

							Kirigami.Separator {
								Layout.fillWidth: true
								visible: index < root.allDevices.length - 1
							}
						}
					}

					PlasmaComponents.Label {
						visible: root.allDevices.length === 0
						text: i18n("No connected devices with battery info found")
						Layout.fillWidth: true
						Layout.topMargin: Kirigami.Units.largeSpacing
						horizontalAlignment: Text.AlignHCenter
						color: Kirigami.Theme.disabledTextColor
					}
				}
			}
		}
	}
}
