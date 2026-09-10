# Changelog

## [Unreleased]

### Added
- **Glorious wireless mouse support** — battery level of the Glorious Model O/O 2/O3, Model D/D-/D 2 PRO and Model I/I 2 wireless mice, read over the vendor HID feature report (`02 02 … 83`) on the mouse's vendor collection. The protocol carries no charging bit, so these mice always report as discharging

## [0.3.2] - 2026-08-22

### Added
- **Keychron M5 support** — new request-response HID schema (0xB3:06 request / 0xB4 reply) reads the M5's battery over the vendor interface; works both wireless (Ultra-Link 8K dongle) and wired (USB-C); correct charging decode
- **Logitech headset support** — battery levels of Logitech G533, G535, G PRO, G733, G933 and G935 headsets, read directly over HID++ request/response; raw battery voltage is mapped to a percentage via per-model calibration curves (protocol details from [HeadsetControl](https://github.com/Sapd/HeadsetControl) and [Solaar](https://github.com/pwr-Solaar-Solaar); not yet verified on real hardware — feedback welcome)
- **ROG Azoth support** — battery level of the ASUS ROG Azoth keyboard over wired USB, the 2.4 GHz dongle and the ROG OMNI receiver, read directly via HID request/response with per-transport report formats (contributed by @LookforFPS)

### Changed
- **User-run udev authorization** — a device whose battery needs extra permission now shows a lock icon and a "Copy command" button; the user pastes one `sudo tee` command in a terminal on their own terms. A single rule file per device covers all its connection variants (wireless + wired)
- **Stateless HID polling** — the helper reports only a current reading each 5s poll, so charging state updates promptly and devices that stop answering (asleep, or a wired mouse's idle dongle) drop immediately instead of showing stale entries

### Contributors
- @MrAdrianPl — reverse-engineered the Keychron M5 battery protocol (hid report probing)
- StarPepe — on-device testing and verification of the M5 support
- @LookforFPS — ROG Azoth battery support (wired USB, 2.4 GHz dongle and OMNI receiver), reverse-engineered on hardware

## [0.3.1] - 2026-07-01

### Added
- **Steam Controller 2 support** — new HID-based provider for the Steam Controller 2; uses a Python helper script to read battery data directly from hidraw (contributed by @valeflare)
- **Charging indicators** — devices now show a charging icon/indicator in both the popup and the tray
- **Configurable tray icon gap** — new setting to adjust the spacing between tray icons
- **Informational tooltip buttons** added to settings sections where they were missing
- **Czech translation** (by @valeflare)
- **Russian translation** (by @d-devy)

### Changed
- HID reader generalised and abstracted; renamed from `read_hid_sc2` to `read_hid_devices` to support multiple device types
- Text box widths changed from static to dynamic sizing
- Translations updated for Hungarian, Dutch, Polish (AI-assisted)

### Fixed
- Charging indicator font styling and spacing/tooltip consistency
- Charging tray icon on vertical panels
- KDE Connect provider no longer fails when `qdbus` is unavailable
- Fixed charging indicator for UPower devices

### Contributors
- @valeflare — Steam Controller 2 provider, HID generalisation, Czech translation
- @d-devy — Russian translation


## [0.3.0] - 2026-05-16

### Added
- **KDE Connect integration** — monitor battery levels of your paired KDE Connect devices directly from the widget; supports unpair action
- **OpenRazer integration** — Razer wireless peripherals now show battery levels (contributed by @TheDogORB)
- **Appearance settings** — customize font family, font size, and icon size for the tray display (contributed by @TheDogORB)
- **Battery color zones** — set custom colors for charging, warning, and critical battery levels with configurable thresholds (contributed by @TheDogORB)
- **Debug mode** — available in Advanced Settings for troubleshooting (contributed by @TheDogORB)

### Changed
- Disconnect/unpair actions are now owned by each provider — adding new integrations no longer requires touching the main UI
- Configuration naming and labels cleaned up for consistency
- Translations updated and completed for Hebrew, Hungarian, Dutch, and Polish

### Contributors
- @TheDogORB — OpenRazer provider, appearance settings, color zones, debug mode

## [0.2.2] - 2026-03-25

### Changed
- Updated Hungarian translation (by @smileyhead)
- Updated Dutch translation (by @Vistaus)

## [0.2.1] - 2026-03-24

### Added
- **Appearance settings** — customize font and icon sizes for device displays via a new config page
- **Vertical panel support** — device names and battery levels now align correctly when the widget is placed in a vertical panel

### Fixed
- Added device type override for Logitech G Pro X mice (by @xTeixeira)
- Refined OpenLinkHub configuration UI
- Updated Hebrew translation

### Contributors
- @xTeixeira

## [0.2.0] - 2026-02-13

### Added
- **Localization support** — the widget is now fully translatable
- Hungarian translation (by @smileyhead)
- Polish translation (by @AzraelBunn)
- Dutch translation (by @Vistaus)

### Fixed
- Fixed disappearing devices (by @AzraelBunn)

### Contributors
- @smileyhead, @AzraelBunn, @Vistaus

## [0.1.0] - 2025-11-30

Initial development releases (v0.1.0 – v0.1.9, through 2026-01-03). Core functionality: monitor battery levels of Bluetooth and wireless devices via UPower, with OpenLinkHub and BatteryWatch Companion integration.

[Unreleased]: https://github.com/itayavra/batterywatch/compare/v0.3.1...HEAD
[0.3.2]: https://github.com/itayavra/batterywatch/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/itayavra/batterywatch/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/itayavra/batterywatch/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/itayavra/batterywatch/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/itayavra/batterywatch/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/itayavra/batterywatch/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/itayavra/batterywatch/releases/tag/v0.1.0
