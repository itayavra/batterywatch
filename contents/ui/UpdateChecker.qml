import QtQuick 2.0

QtObject {
    id: root

    property bool enabled: true
    property string currentVersion: ""
    property string latestVersion: ""
    property bool updateAvailable: false
    property bool checkInProgress: false
    property string releaseNotesUrl: "https://github.com/itayavra/batterywatch/releases/latest"

    function versionParts(version) {
        return String(version || "").replace(/^v/i, "").split(".").map(function(part) {
            return parseInt(part, 10) || 0;
        });
    }

    function isNewerVersion(candidate, current) {
        var a = versionParts(candidate);
        var b = versionParts(current);
        var length = Math.max(a.length, b.length);
        for (var i = 0; i < length; i++) {
            var left = a[i] || 0;
            var right = b[i] || 0;
            if (left > right)
                return true;
            if (left < right)
                return false;
        }
        return false;
    }

    function checkForUpdates() {
        if (!enabled || checkInProgress || !currentVersion)
            return;

        checkInProgress = true;

        var xhr = new XMLHttpRequest();
        xhr.open("GET", "https://api.github.com/repos/itayavra/batterywatch/releases/latest");
        xhr.timeout = 10000;
        try {
            xhr.setRequestHeader("Accept", "application/vnd.github+json");
        } catch (e) {
        }

        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE)
                return;

            checkInProgress = false;
            if (xhr.status !== 200)
                return;

            var data;
            try {
                data = JSON.parse(xhr.responseText);
            } catch (e) {
                return;
            }

            if (!data || data.draft)
                return;

            var tag = data.tag_name || data.name || "";
            if (!tag)
                return;

            latestVersion = tag.replace(/^v/i, "");
            releaseNotesUrl = data.html_url || releaseNotesUrl;
            updateAvailable = isNewerVersion(latestVersion, currentVersion);
        };

        xhr.send();
    }

    onEnabledChanged: {
        if (enabled)
            checkForUpdates();
    }

    Component.onCompleted: checkForUpdates()

    property Timer updateTimer: Timer {
        interval: 24 * 60 * 60 * 1000
        repeat: true
        running: root.enabled
        onTriggered: root.checkForUpdates()
    }
}
