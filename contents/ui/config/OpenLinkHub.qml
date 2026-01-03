import QtQuick 2.0
import QtQuick.Controls 2.5 as QQC2
import org.kde.kirigami 2.4 as Kirigami
import org.kde.kcmutils as KCMUtils

KCMUtils.SimpleKCM {
	id: root

	property alias cfg_enableOpenLinkHubIntegration: enableOpenLinkHubIntegration.checked
	property alias cfg_openLinkHubApiPort: openLinkHubApiPort.value

	Kirigami.FormLayout {
		id: page

        anchors.left: parent.left
        anchors.right: parent.right

		QQC2.CheckBox {
			id: enableOpenLinkHubIntegration
			Kirigami.FormData.label: i18n("Enable OpenLinkHub Integration: ")
			text: i18n("Enabled")
		}
		
		QQC2.SpinBox {
			id: openLinkHubApiPort
			Kirigami.FormData.label: i18n("OpenLinkHub Port: ")
			to: 65535
		}

	}
}