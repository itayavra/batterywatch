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

- **Unified Monitoring** - see battery levels of all your devices in one place, right in your system tray
- **Smart Display** - minimal tray icon that expands into a detailed list on click, and auto-hides when no devices are connected
- **Customizable Appearance** - configure font family, font size, icon size, and per-level battery colors (charging, warning, critical)
- **Customizable Visibility** - hide or show specific devices to keep your tray clutter-free

## Supported Integrations

| Provider | What it covers |
|----------|----------------|
| **UPower** | Bluetooth and wireless peripherals reported by the system - headphones, mice, keyboards, game controllers, and more |
| **OpenLinkHub** | Corsair and other devices managed by [OpenLinkHub](https://github.com/jurkovic-nikola/OpenLinkHub) |
| **OpenRazer** | Razer peripherals via [OpenRazer](https://openrazer.github.io/) |
| **KDE Connect** | Battery levels of paired KDE Connect devices (phones, tablets, etc), with easy unpair action |

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

## Support the Project

If BatteryWatch saves you from digging through menus just to check your headphone battery, consider buying me a coffee - I maintain this in my spare time and it genuinely helps!

<a href="https://www.buymeacoffee.com/itayavra" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

## Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/itayavra/batterywatch/issues).

For instructions on how to contribute translations, add new languages, or test current ones, please refer to the [Translation Guide](translate/README.md).
## Supported Languages

<!-- TRANSLATIONS_START -->
| Locale | Language | Status | % Done |
|--------|----------|--------|--------|
| cs     | Cs           | 🟡 In Progress |    96% |
| he     | Hebrew       | ✅ Complete |   100% |
| hu     | Hungarian    | ✅ Complete |   100% |
| nl     | Dutch        | ✅ Complete |   100% |
| pl     | polish       | ✅ Complete |   100% |
| ru     | Ru           | 🟡 In Progress |    96% |
<!-- TRANSLATIONS_END -->


