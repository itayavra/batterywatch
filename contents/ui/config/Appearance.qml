import QtQuick 2.0
import QtQuick.Controls 2.5 as QQC2
import QtQuick.Layouts 1.1
import org.kde.kirigami 2.4 as Kirigami
import org.kde.kcmutils as KCMUtils

KCMUtils.SimpleKCM {
	id: root

	property alias cfg_useCustomFontSize: useCustomFontSize.checked
	property alias cfg_useCustomIconSize: useCustomIconSize.checked
	property alias cfg_customFontSize: customFontSize.value
	property alias cfg_customIconSize: customIconSize.value

	Kirigami.FormLayout {
		id: page

		anchors.left: parent.left
		anchors.right: parent.right

		QQC2.CheckBox {
			id: useCustomFontSize
			Kirigami.FormData.label: i18n("Custom Font Size: ")
			text: i18n("Enabled")
		}

		QQC2.SpinBox {
			id: customFontSize
			Kirigami.FormData.label: i18n("Size (px): ")
			from: 4
			to: 72
			enabled: useCustomFontSize.checked
		}

		QQC2.CheckBox {
			id: useCustomIconSize
			Kirigami.FormData.label: i18n("Custom Device Icon Size: ")
			text: i18n("Enabled")
		}

		QQC2.SpinBox {
			id: customIconSize
			Kirigami.FormData.label: i18n("Size (px): ")
			from: 8
			to: 128
			enabled: useCustomIconSize.checked
		}
	}
}
