import QtQuick 2.0
import QtQuick.Layouts 1.1

import org.kde.plasma.components 3.0 as PlasmaComponents
import org.kde.kirigami 2.4 as Kirigami

Rectangle {
    id: root

    property string latestVersion: ""

    signal download()
    signal dismiss()

    Layout.alignment: Qt.AlignVCenter
    implicitWidth: updatePillRow.implicitWidth + Kirigami.Units.largeSpacing
    implicitHeight: updatePillRow.implicitHeight + Kirigami.Units.smallSpacing
    radius: height / 2
    color: Qt.rgba(Kirigami.Theme.highlightColor.r,
                   Kirigami.Theme.highlightColor.g,
                   Kirigami.Theme.highlightColor.b,
                   updatePillMouse.containsMouse ? 0.32 : 0.18)

    MouseArea {
        id: updatePillMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.download()

        PlasmaComponents.ToolTip {
            visible: updatePillMouse.containsMouse && !updatePillDismiss.hovered
            text: i18n("BatteryWatch v%1 is available — click to download", root.latestVersion)
        }
    }

    RowLayout {
        id: updatePillRow
        anchors.centerIn: parent
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Icon {
            source: "download"
            Layout.preferredWidth: Kirigami.Units.iconSizes.small
            Layout.preferredHeight: Kirigami.Units.iconSizes.small
        }

        PlasmaComponents.Label {
            text: i18n("Update v%1", root.latestVersion)
            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
        }

        PlasmaComponents.ToolButton {
            id: updatePillDismiss
            icon.name: "dialog-close"
            display: PlasmaComponents.AbstractButton.IconOnly
            text: i18n("Dismiss")
            Layout.preferredWidth: Kirigami.Units.iconSizes.small
            Layout.preferredHeight: Kirigami.Units.iconSizes.small
            onClicked: root.dismiss()

            PlasmaComponents.ToolTip {
                text: i18n("Hide until the next update")
            }

            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onPressed: mouse.accepted = false
            }
        }
    }
}
