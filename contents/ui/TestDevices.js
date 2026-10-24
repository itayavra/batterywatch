// Fake devices shown alongside the real ones when debug mode is on.
var testDevices = [
    // Headphones with 3 batteries
    {
        name: "Headphones",
        serial: "test-1",
        icon: "audio-headphones",
        batteries: [
            {
                label: "Left",
                percentage: 50,
                charging: true
            },
            {
                label: "Right",
                percentage: 30,
                charging: false
            },
            {
                label: "Case",
                percentage: 10,
                charging: false
            }
        ]
    },
    {
        name: "Mouse",
        serial: "Mouse-test",
        icon: "input-mouse",
        percentage: 50,
        charging: true
    },
    {
        name: "Keyboard",
        serial: "Keyboard-test-warning",
        icon: "input-keyboard",
        percentage: 30,
        charging: false
    },
    {
        name: "Gamepad",
        serial: "Gamepad-test-critical",
        icon: "input-gamepad",
        percentage: 10,
        charging: false
    }
]
