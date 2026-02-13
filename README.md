# BatteryWatch

[![Latest Release](https://img.shields.io/github/v/release/itayavra/batterywatch?color=4CAF50&label=Latest%20release&style=for-the-badge)](https://github.com/itayavra/batterywatch/releases)
[![KDE Plasma 6](https://img.shields.io/badge/KDE-Plasma%206-blue?style=for-the-badge)](https://store.kde.org/p/2331781)
[![License](https://img.shields.io/badge/license-GPL--3.0-green?style=for-the-badge)](https://github.com/itayavra/batterywatch/blob/master/LICENSE)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow.svg?style=for-the-badge&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/itayavra)
---

**BatteryWatch** is a sleek, modern KDE Plasma 6 widget designed to monitor your device's power ecosystem. Keep track of battery levels for your Bluetooth or wireless devices, like headphones, mouse, keyboard, and game controllers, all from a single, beautiful interface right there in your tray bar!

## Screenshots

![BatteryWatch Screenshot 1](contents/screenshots/screenshot1.png)

![BatteryWatch Screenshot 2](contents/screenshots/screenshot2.png)

![BatteryWatch Screenshot 3](contents/screenshots/screenshot3.png)

## Features

*   **Unified Monitoring**: See the battery status of all connected devices in one place.
*   **Smart Display**: A minimal tray icon that expands into a detailed list when clicked, and automatically hides when no devices are connected - no wasted space when nothing to show.
*   **Bluetooth Control**: Disconnect Bluetooth devices directly from the widget.
*   **Customizable Visibility**: Easily hide or show specific devices from the system tray to keep your workspace clutter-free.

## Installation

### From the KDE Store (Recommended)
1.  Right-click on your desktop or panel.
2.  Select **Add Widgets...**
3.  Click **Get New Widgets...** -> **Download New Plasma Widgets**.
4.  Search for **"BatteryWatch"** and click **Install**.

### Manual Installation
1.  Download the latest `.plasmoid` release from the [Releases](https://github.com/itayavra/batterywatch/releases) page.
2.  Run the following command:
    ```bash
    kpackagetool6 --type Plasma/Applet --install BatteryWatch.plasmoid
    ```

## Building from Source

```bash
git clone https://github.com/itayavra/batterywatch.git
cd batterywatch
# Zip the contents to create the plasmoid
zip -r BatteryWatch.plasmoid .
# Install
kpackagetool6 --type Plasma/Applet --install BatteryWatch.plasmoid
```

## Development

```bash
# Install development version
./dev-install.sh

# Restart Plasma Shell to reload changes
./dev-restart-plasma.sh

# Uninstall development version
./dev-uninstall.sh
```

## Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/itayavra/batterywatch/issues).

For instructions on how to contribute translations, add new languages, or test current ones, please refer to the [Translation Guide](translate/README.md).
## Supported Languages

<!-- TRANSLATIONS_START -->
| Locale | Language | Status | % Done |
|--------|----------|--------|--------|
| he     | Hebrew       | ✅ Complete |   100% |
| hu     | Hungarian    | ✅ Complete |   100% |
| nl     | Dutch        | ✅ Complete |   100% |
| pl     | polish       | ✅ Complete |   100% |
<!-- TRANSLATIONS_END -->

## Support the Project ❤️

If you find BatteryWatch useful and want to support its development, consider buying me a coffee 🫶 ☕

<a href="https://www.buymeacoffee.com/itayavra" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

