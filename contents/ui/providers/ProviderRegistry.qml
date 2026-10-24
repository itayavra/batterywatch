import QtQuick 2.15

// Providers declared inside are registered automatically. The declaration
// order is the merge priority: the first provider to report a device wins.
QtObject {
    default property list<QtObject> providers

    function devicesByPriority() {
        var lists = []
        for (var i = 0; i < providers.length; i++)
            lists.push(providers[i].devices)
        return lists
    }

    function refreshAll() {
        for (var i = 0; i < providers.length; i++)
            providers[i].refresh()
    }
}
