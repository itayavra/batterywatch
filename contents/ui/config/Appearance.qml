import QtQuick 2.0
import QtQuick.Controls 2.5 as QQC2
import QtQuick.Layouts 1.1 as QQL
import org.kde.kquickcontrols as KQC

import org.kde.kirigami 2.4 as Kirigami
import org.kde.kcmutils as KCMUtils

KCMUtils.SimpleKCM {
    id: root

    property alias cfg_fontFamily: page.cfg_fontFamily
    property alias cfg_fontBold: boldCheckBox.checked
    property alias cfg_fontWeight: fontWeight.value
    property alias cfg_fontItalic: italicCheckBox.checked
    property alias cfg_useCustomFontSize: useCustomFontSize.checked
    property alias cfg_customFontSize: customFontSize.value
    property alias cfg_useCustomIconSize: useCustomIconSize.checked
    property alias cfg_customIconSize: customIconSize.value
    property alias cfg_useCustomTraySpacing: useCustomTraySpacing.checked
    property alias cfg_customTraySpacing: customTraySpacing.value
    // Color
    property alias cfg_useCustomDefaultColor: useCustomDefaultColor.checked
    property alias cfg_customDefaultColor: customDefaultColor.color

    property alias cfg_useChargingColor: useChargingColor.checked
    property alias cfg_chargingColor: chargingColor.color
    property alias cfg_showTrayChargingIndicator: showChargingIndicator.checked

    property alias cfg_zoneOneColor: zoneOneColor.color
    property alias cfg_useZoneOneColor: useZoneOneColor.checked
    property alias cfg_zoneOneThreshold: zoneOneThreshold.value

    property alias cfg_zoneTwoColor: zoneTwoColor.color
    property alias cfg_useZoneTwoColor: useZoneTwoColor.checked
    property alias cfg_zoneTwoThreshold: zoneTwoThreshold.value

    Kirigami.FormLayout {
        id: page

        // anchors.left: parent.left
        // anchors.right: parent.right

        // Bound to SimpleKCM cfg_fontFamily - "" = "System default"
        property string cfg_fontFamily
        // Shared width for all Spinboxes and Gridboxes
        readonly property int boxWidth: Kirigami.Units.gridUnit * 3
        readonly property int boxHeight: Kirigami.Units.gridUnit * 1.5

        // Fetches fonts
        ListModel {
            id: fontsModel

            Component.onCompleted: {
                const systemFont = Kirigami.Theme.defaultFont.family;
                const fonts = Qt.fontFamilies();
                const arr = [
                    {
                        // Empty value keeps sys default font
                        text: i18n("System Default (%1)", systemFont),
                        value: ""
                    }
                ];

                for (let i = 0, fontCount = fonts.length; i < fontCount; ++i) {
                    arr.push({
                        text: fonts[i],
                        value: fonts[i]
                    });
                }

                append(arr);
            }
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Tray Settings")
            QQL.Layout.fillWidth: true
        }

        QQL.RowLayout {
            QQL.Layout.fillWidth: true
            Kirigami.FormData.label: i18n("Font family:")
            QQL.Layout.preferredWidth: styleRowLayout.implicitWidth

            QQC2.ComboBox {
                id: fontFamily
                model: fontsModel
                textRole: "text"
                valueRole: "value"
                currentValue: page.cfg_fontFamily

                QQL.Layout.fillWidth: true

                // Does not autosync -> updat explicitly on change
                onCurrentValueChanged: {
                    page.cfg_fontFamily = currentValue;
                }
            }

            QQC2.ToolButton {
                id: fontFamilyHelp
                icon.name: "help-about"

                QQC2.ToolTip {
                    visible: fontFamilyHelp.hovered
                    text: i18n("Change the font family used for system tray text.")
                }
            }
        }

        QQL.RowLayout {
            id: styleRowLayout
            Kirigami.FormData.label: i18n("Style")
            QQL.Layout.fillWidth: true

            QQC2.CheckBox {
                id: boldCheckBox
                text: i18n("Bold")
                QQL.Layout.preferredWidth: Math.max(implicitWidth, useCustomFontSize.implicitWidth)
            }

            QQC2.SpinBox {
                // CSS / Qt scale: 100 - 1000
                id: fontWeight
                enabled: boldCheckBox.checked
                from: 100
                to: 1000
                stepSize: 100

                QQL.Layout.preferredWidth: page.boxWidth
            }

            QQC2.ToolButton {
                id: boldHelp
                icon.name: "help-about"

                QQC2.ToolTip {
                    visible: boldHelp.hovered
                    text: i18n("Make the tray text bold.\nAdjust weight between 100 and 1000.")
                }
            }

            QQC2.CheckBox {
                id: italicCheckBox
                text: i18n("Italic")
                QQL.Layout.preferredWidth: Math.max(implicitWidth, useCustomIconSize.implicitWidth)
            }

            // Invisible "italic spinbox" for the help icon to align properly
            QQC2.SpinBox {
                opacity: 0
                enabled: false

                QQL.Layout.preferredWidth: page.boxWidth
            }

            QQC2.ToolButton {
                id: italicHelp
                icon.name: "help-about"

                QQC2.ToolTip {
                    visible: italicHelp.hovered
                    text: i18n("Make the tray text italic.")
                }
            }
        }

        QQL.RowLayout {
            Kirigami.FormData.label: i18n("Sizes")
            QQL.Layout.fillWidth: true
            QQC2.CheckBox {
                id: useCustomFontSize
                text: i18n("Font")
                QQL.Layout.preferredWidth: Math.max(implicitWidth, boldCheckBox.implicitWidth)
            }

            QQC2.SpinBox {
                id: customFontSize
                enabled: useCustomFontSize.checked
                from: 4
                to: 72

                QQL.Layout.preferredWidth: page.boxWidth
            }

            QQC2.ToolButton {
                id: customFontSizeHelp
                icon.name: "help-about"

                QQC2.ToolTip {
                    visible: customFontSizeHelp.hovered
                    text: i18n("Adjust the size of tray text (in pixels).")
                }
            }

            QQC2.CheckBox {
                id: useCustomIconSize
                text: i18n("Icon")
                QQL.Layout.preferredWidth: Math.max(implicitWidth, italicCheckBox.implicitWidth)
            }

            QQC2.SpinBox {
                id: customIconSize
                enabled: useCustomIconSize.checked
                from: 8
                to: 128

                QQL.Layout.preferredWidth: page.boxWidth
            }
            QQC2.ToolButton {
                id: customIconSizeHelp
                icon.name: "help-about"

                QQC2.ToolTip {
                    visible: customIconSizeHelp.hovered
                    text: i18n("Adjust the size of tray icons (in pixels).")
                }
            }

            QQC2.CheckBox {
                id: useCustomTraySpacing
                text: i18n("Spacing")
            }

            QQC2.SpinBox {
                id: customTraySpacing
                enabled: useCustomTraySpacing.checked
                from: 0
                to: 32
                QQL.Layout.preferredWidth: page.boxWidth
            }
            QQC2.ToolButton {
                id: customTraySpacingHelp
                icon.name: "help-about"
                QQC2.ToolTip {
                    visible: customTraySpacingHelp.hovered
                    text: i18n("Adjust the gap between tray icons (in pixels).")
                }
            }
        }

        Item {
            Kirigami.FormData.label: i18n("Charging indicator")
            implicitWidth: showChargingIndicator.implicitWidth
            implicitHeight: page.boxHeight

            QQC2.CheckBox {
                id: showChargingIndicator
                anchors.verticalCenter: parent.verticalCenter
                text: i18n("Show charging indicator in tray")
            }
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Battery Colors")
            QQL.Layout.fillWidth: true
        }

        QQL.RowLayout {
            Kirigami.FormData.label: i18n("Default")

            QQC2.CheckBox {
                id: useCustomDefaultColor
            }

            KQC.ColorButton {
                id: customDefaultColor
                enabled: useCustomDefaultColor.checked
                showAlphaChannel: true
                QQL.Layout.preferredWidth: page.boxWidth
            }

            QQC2.ToolButton {
                id: defaultColorHelp
                icon.name: "help-about"

                QQC2.ToolTip {
                    visible: defaultColorHelp.hovered
                    text: i18n("Use when no other color state applies. When disabled, system color is used instead.")
                }
            }
        }

        QQL.RowLayout {
            Kirigami.FormData.label: i18n("Charging")

            QQC2.CheckBox {
                id: useChargingColor
            }

            KQC.ColorButton {
                id: chargingColor
                enabled: useChargingColor.checked
                showAlphaChannel: true
                QQL.Layout.preferredWidth: page.boxWidth
            }

            QQC2.ToolButton {
                id: chargingColorHelp
                icon.name: "help-about"

                QQC2.ToolTip {
                    visible: chargingColorHelp.hovered
                    text: i18n("Overrides all other colors when device is charging.\nNot all devices are currently supported!")
                }
            }
        }

        QQL.RowLayout {
            Kirigami.FormData.label: i18n("Zone 1")

            QQC2.CheckBox {
                id: useZoneOneColor

                onCheckedChanged: {
                    if (!checked) {
                        useZoneTwoColor.checked = false;
                    }
                }
            }

            KQC.ColorButton {
                id: zoneOneColor
                enabled: useZoneOneColor.checked
                showAlphaChannel: true
                QQL.Layout.preferredWidth: page.boxWidth
            }

            QQC2.Label {
                opacity: useZoneOneColor.checked ? 0.8 : 0.5
                text: i18n("≤")
                font.pixelSize: Kirigami.Theme.defaultFont.pixelSize * 1.4
                font.weight: Font.Medium

                QQL.Layout.leftMargin: 4
                QQL.Layout.rightMargin: 4

                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            QQC2.SpinBox {
                id: zoneOneThreshold
                enabled: useZoneOneColor.checked
                from: 1
                to: 100
                QQL.Layout.preferredWidth: page.boxWidth
            }

            QQC2.Label {
                opacity: useZoneOneColor.checked ? 0.8 : 0.5
                text: i18n("%")
            }

            QQC2.ToolButton {
                id: zoneOneHelp
                icon.name: "help-about"

                QQC2.ToolTip {
                    visible: zoneOneHelp.hovered
                    text: i18n("Applied when battery falls below the set threshold.")
                }
            }
        }

        QQL.RowLayout {
            Kirigami.FormData.label: i18n("Zone 2")

            QQC2.CheckBox {
                id: useZoneTwoColor
                enabled: useZoneOneColor.checked
            }

            KQC.ColorButton {
                id: zoneTwoColor
                enabled: useZoneOneColor.checked && useZoneTwoColor.checked
                showAlphaChannel: true
                QQL.Layout.preferredWidth: page.boxWidth
            }

            QQC2.Label {
                opacity: useZoneTwoColor.checked ? 0.8 : 0.5
                text: i18n("≤")
                font.pixelSize: Kirigami.Theme.defaultFont.pixelSize * 1.4
                font.weight: Font.Medium

                QQL.Layout.leftMargin: 4
                QQL.Layout.rightMargin: 4

                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }

            QQC2.SpinBox {
                id: zoneTwoThreshold
                enabled: useZoneOneColor.checked && useZoneTwoColor.checked
                from: 0
                to: 100
                QQL.Layout.preferredWidth: page.boxWidth
            }

            QQC2.Label {
                opacity: useZoneTwoColor.checked ? 0.8 : 0.5
                text: i18n("%")
            }

            QQC2.ToolButton {
                id: zoneTwoHelp
                icon.name: "help-about"

                QQC2.ToolTip {
                    visible: zoneTwoHelp.hovered
                    text: i18n("Applied when battery falls below the set threshold.")
                }
            }
        }
    }
}
