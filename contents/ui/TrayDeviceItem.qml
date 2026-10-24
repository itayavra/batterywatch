import QtQuick
import QtQuick.Layouts

import org.kde.plasma.plasmoid 2.0
import org.kde.plasma.components 3.0 as PlasmaComponents
import org.kde.kirigami 2.20 as Kirigami

GridLayout {
    id: root

    property var device: ({})
    property color batteryColor: Kirigami.Theme.textColor

    rowSpacing: 2
    columnSpacing: 2

    Kirigami.Icon {
        source: root.device.icon
        Layout.preferredWidth: Plasmoid.configuration.useCustomIconSize ? Plasmoid.configuration.customIconSize : Kirigami.Units.iconSizes.smallMedium
        Layout.preferredHeight: Plasmoid.configuration.useCustomIconSize ? Plasmoid.configuration.customIconSize : Kirigami.Units.iconSizes.smallMedium
        Layout.alignment: Qt.AlignCenter
    }

    PlasmaComponents.Label {
        // i18n: %1 is the charge percentage value; the trailing % is a literal percent sign.
        text: i18n("%1%", root.device.percentage)
        color: root.batteryColor
        font.family: Plasmoid.configuration.fontFamily !== "" ? Plasmoid.configuration.fontFamily : Kirigami.Theme.smallFont.family
        font.weight: Plasmoid.configuration.fontBold ? Plasmoid.configuration.fontWeight : Font.Normal
        font.italic: Plasmoid.configuration.fontItalic
        font.pixelSize: Plasmoid.configuration.useCustomFontSize ? Plasmoid.configuration.customFontSize : Kirigami.Theme.smallFont.pixelSize
        Layout.alignment: Qt.AlignCenter
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    PlasmaComponents.Label {
        visible: Plasmoid.configuration.showTrayChargingIndicator && root.device.charging
        text: "⚡︎"
        color: root.batteryColor
        font.family: Plasmoid.configuration.fontFamily !== "" ? Plasmoid.configuration.fontFamily : Kirigami.Theme.smallFont.family
        font.weight: Plasmoid.configuration.fontBold ? Plasmoid.configuration.fontWeight : Font.Normal
        font.italic: Plasmoid.configuration.fontItalic
        font.pixelSize: Plasmoid.configuration.useCustomFontSize ? Plasmoid.configuration.customFontSize : Kirigami.Theme.smallFont.pixelSize
        Layout.alignment: Qt.AlignCenter
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
