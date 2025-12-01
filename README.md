# BatteryWatch 🔋

**BatteryWatch** is a sleek, modern KDE Plasma 6 widget designed to monitor your device's power ecosystem. Keep track of battery levels for your Bluetooth or wireless devices, like headphones, mouse, keyboard, and game controllers, all from a single, beautiful interface right there in your tray bar!

## Screenshots

![BatteryWatch Screenshot 1](contents/screenshots/screenshot1.png)

![BatteryWatch Screenshot 2](contents/screenshots/screenshot2.png)

![BatteryWatch Screenshot 3](contents/screenshots/screenshot3.png)

## ✨ Features

*   **Unified Monitoring**: See the battery status of all connected devices in one place.
*   **Smart Display**: A minimal tray icon that expands into a detailed list when clicked, and automatically hides when no devices are connected — no wasted space when nothing to show.
*   **Bluetooth Control**: Disconnect Bluetooth devices directly from the widget.
*   **Customizable Visibility**: Easily hide or show specific devices from the system tray to keep your workspace clutter-free.

## 📥 Installation

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

## 🛠️ Building from Source

```bash
git clone https://github.com/itayavra/batterywatch.git
cd batterywatch
# Zip the contents to create the plasmoid
zip -r BatteryWatch.plasmoid .
# Install
kpackagetool6 --type Plasma/Applet --install BatteryWatch.plasmoid
```

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/itayavra/batterywatch/issues).

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
