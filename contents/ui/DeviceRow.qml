import QtQuick 2.0
import QtQuick.Layouts 1.1

import org.kde.plasma.components 3.0 as PlasmaComponents
import org.kde.kirigami 2.4 as Kirigami

ColumnLayout {
    id: root

    property var device: ({})
    property int rowIndex: 0
    property int rowCount: 0
    property bool hidden: false
    property bool notificationMuted: false
    property bool notificationEnabled: false
    property bool commandCopied: false

    signal disconnectRequested()
    signal copyUnblockCommandRequested()
    signal toggleVisibilityRequested()
    signal toggleNotificationRequested()

    property var batteryColor: function(percentage, charging) { return Kirigami.Theme.textColor }

    Layout.fillWidth: true
    spacing: 0

    property bool hasMultipleBatteries: device.batteries && device.batteries.length > 1

    Item {
        Layout.fillWidth: true
        Layout.preferredHeight: device.blocked === true ? Kirigami.Units.gridUnit * 5 : Kirigami.Units.gridUnit * 4
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

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        visible: device.blocked === true
                        source: "object-locked"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.small
                        Layout.preferredHeight: Kirigami.Units.iconSizes.small
                        Layout.alignment: Qt.AlignVCenter
                    }

                    PlasmaComponents.Label {
                        text: device.name || i18n("Unknown Device")
                        font.bold: true
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                }

                PlasmaComponents.Label {
                    text: device.blocked === true ? i18n("Permission needed - run the command in a terminal") : device.serial
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    color: device.blocked === true ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.disabledTextColor
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    wrapMode: device.blocked === true ? Text.WordWrap : Text.NoWrap
                }

                RowLayout {
                    visible: hasMultipleBatteries
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.largeSpacing

                    Repeater {
                        model: hasMultipleBatteries ? device.batteries : []

                        PlasmaComponents.Label {
                            textFormat: Text.RichText
                            text: {
                                var bat = modelData;
                                var label = bat.label || i18n("Battery");
                                var charging = bat.charging ? " ⚡" : "";
                                var color = root.batteryColor(bat.percentage, bat.charging);
                                return i18n("%1: <span style=\"color:%4\">%2%</span>%3", label, bat.percentage, charging, color);
                            }
                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        }
                    }
                }
            }

            RowLayout {
                Layout.alignment: Qt.AlignVCenter

                PlasmaComponents.ToolButton {
                    visible: typeof device.disconnect === "function"
                    icon.name: "network-disconnect"
                    text: i18n("Disconnect")
                    display: PlasmaComponents.AbstractButton.IconOnly
                    onClicked: {
                        if (typeof device.disconnect === "function") {
                            device.disconnect()
                        }
                        root.disconnectRequested()
                    }

                    PlasmaComponents.ToolTip {
                        text: device.disconnectTooltip || i18n("Disconnect device")
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onPressed: mouse.accepted = false
                    }
                }

                PlasmaComponents.ToolButton {
                    visible: device.blocked !== true
                    icon.name: root.hidden ? "view-hidden" : "view-visible"
                    text: root.hidden ? i18n("Show") : i18n("Hide")
                    display: PlasmaComponents.AbstractButton.IconOnly
                    onClicked: root.toggleVisibilityRequested()

                    PlasmaComponents.ToolTip {
                        text: root.hidden ? i18n("Show in tray") : i18n("Hide from tray")
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onPressed: mouse.accepted = false
                    }
                }

                PlasmaComponents.ToolButton {
                    visible: notificationEnabled
                    icon.name: root.notificationMuted ? "notification-disabled" : "notification-active"
                    text: root.notificationMuted ? i18n("Enable Notification") : i18n("Disable Notification")
                    display: PlasmaComponents.AbstractButton.IconOnly
                    onClicked: root.toggleNotificationRequested()

                    PlasmaComponents.ToolTip {
                        text: root.notificationMuted ? i18n("Enable Notification") : i18n("Disable Notification")
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onPressed: mouse.accepted = false
                    }
                }

                PlasmaComponents.Button {
                    visible: device.blocked === true
                    flat: true
                    icon.name: root.commandCopied ? "checkmark" : "edit-copy"
                    text: root.commandCopied ? i18n("Copied!") : i18n("Copy command")
                    onClicked: root.copyUnblockCommandRequested()

                    PlasmaComponents.ToolTip {
                        text: root.commandCopied ? i18n("Copied to clipboard") : i18n("Copy the command to run in a terminal")
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onPressed: mouse.accepted = false
                    }
                }

                PlasmaComponents.Label {
                    visible: !hasMultipleBatteries && device.blocked !== true
                    text: i18n("%1%%2", device.percentage, device.charging ? " ⚡" : "")
                    color: root.batteryColor(device.percentage, device.charging)
                    font.bold: true
                    Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                    horizontalAlignment: Text.AlignRight
                }
            }
        }
    }

    Kirigami.Separator {
        Layout.fillWidth: true
        visible: root.rowIndex < root.rowCount - 1
    }
}
