import QtQuick 2.0
import org.kde.plasma.configuration 2.0

ConfigModel {
	ConfigCategory {
		name: i18n("Appearance")
		icon: "preferences-desktop-appearance"
		source: "config/Appearance.qml"
	}
	ConfigCategory {
		name: i18n("OpenLinkHub Integration")
		icon: "network-connect"
		source: "config/OpenLinkHub.qml"
	}
}
