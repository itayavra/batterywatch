import QtQuick 2.0
import org.kde.plasma.configuration 2.0

ConfigModel {
    ConfigCategory {
        name: i18n("Appearance")
        icon: "preferences-desktop-color"
        source: "config/Appearance.qml"
    }
    ConfigCategory {
        name: i18n("Integrations")
        icon: "network-connect"
        source: "config/Modules.qml"
    }
    ConfigCategory {
        name: i18n("Notification")
        icon: "notification-active"
        source: "config/Notifications.qml"
    }
    ConfigCategory {
        name: i18n("Updates")
        icon: "system-software-update"
        source: "config/Updates.qml"
    }
    ConfigCategory {
        name: i18n("Advanced settings")
        icon: "settings-configure"
        source: "config/AdvancedSettings.qml"
    }
}
