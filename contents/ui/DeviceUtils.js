
// Shared device utilities

function getIconForType(deviceType) {
    switch (deviceType) {
        case "gaming-input":
        case "gamepad":
            return "input-gamepad"
        case "mouse":
            return "input-mouse"
        case "touchpad":
            return "input-touchpad"
        case "keyboard":
            return "input-keyboard"
        case "phone":
        case "smartphone":
            return "smartphone"
        case "tablet":
            return "tablet"
        case "headphones":
            return "audio-headphones"
        case "headset":
            return "audio-headset"
        case "monitor":
        case "display":
            return "video-display"
        default:
            return "battery-symbolic"
    }
}
