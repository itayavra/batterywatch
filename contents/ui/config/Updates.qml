import QtQuick 2.0
import QtQuick.Controls 2.5 as QQC2
import QtQuick.Layouts 1.1 as QQL

import org.kde.kirigami 2.4 as Kirigami
import org.kde.kcmutils as KCMUtils

KCMUtils.SimpleKCM {
    id: root

    property alias cfg_updateCheckEnabled: updateCheckEnabled.checked
    property alias cfg_updateNotifyTooltip: updateNotifyTooltip.checked
    property alias cfg_updateNotifyInlineMessage: updateNotifyInlineMessage.checked

    Kirigami.FormLayout {
        id: page

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Update checks")
        }

        QQL.RowLayout {
            Kirigami.FormData.label: i18n("Check for updates")

            QQC2.CheckBox {
                id: updateCheckEnabled
            }

            QQC2.ToolButton {
                id: updateCheckHelp
                icon.name: "help-about"

                QQC2.ToolTip {
                    visible: updateCheckHelp.hovered
                    text: i18n("Periodically asks GitHub for the latest BatteryWatch release. No data is sent.")
                }
            }
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("How to notify")
        }

        QQL.RowLayout {
            Kirigami.FormData.label: i18n("Tooltip hint")

            QQC2.CheckBox {
                id: updateNotifyTooltip
                enabled: updateCheckEnabled.checked
            }

            QQC2.Label {
                text: i18n("(Update available) appended when hovering the tray icon")
                opacity: updateNotifyTooltip.enabled ? 0.7 : 0.5
            }
        }

        QQL.RowLayout {
            Kirigami.FormData.label: i18n("Header pill")

            QQC2.CheckBox {
                id: updateNotifyInlineMessage
                enabled: updateCheckEnabled.checked
            }

            QQC2.Label {
                text: i18n("Dismissible download chip in the popup header")
                opacity: updateNotifyInlineMessage.enabled ? 0.7 : 0.5
            }
        }
    }
}
