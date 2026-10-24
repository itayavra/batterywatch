# Changelog

## [Unreleased]

### Added
- **BlueZ integration** — battery percentage of connected Bluetooth devices that report battery to BlueZ but not to UPower (e.g. 8bitdo controllers), read through `bluetoothctl` with a configurable polling interval (default 5s) and a disconnect action. Charging is reported as unknown rather than "not charging", so a provider that knows the state fills it in (contributed by @birrkan)
- **Low-battery notifications** — enable alerts, and set a battery threshold; use the popup's bell toggle to mute individual devices. BatteryWatch sends one system notification when a monitored battery is at or below the threshold and not charging; it can alert again after the battery rises above the threshold and later drops low again. Muted devices are saved across restarts (contributed by @YourM4jesty, issue #60)
- **Glorious wireless mouse support** — battery level of the Glorious Model O/O 2/O3, Model D/D-/D 2 PRO and Model I 2 wireless mice, read over HID feature reports. Tested on a Model O Wireless. The protocol provides no charging state, including over USB, so charging remains unknown unless another provider supplies it. Feature-report exchanges have a two-second deadline so an unresponsive mouse does not delay other HID readings (contributed by @Quintisimo, PR #46)
- **Corsair K57 RGB Wireless support** - battery percentage and charging state of the keyboard through its own USB dongle (1b1c:1b62), read directly via three Bragi GET requests on the dongle's command interface (interface 1): the dongle's paired-device list first, then the keyboard's battery level and battery status, so the keyboard is never asked while it is not linked. Every reply must start with the child index of the asked address (0x00 from the dongle, 0x01 from the keyboard, as the dongle sends it) or with the address itself, and carry the GET command, a success status and a valid value before anything is decoded. Only GET is ever sent: no setting is written and software mode is never entered
- **HeadsetControl integration** — battery percentage and charging state of headsets supported by [HeadsetControl](https://github.com/Sapd/HeadsetControl), read from its `-b -o json` output with a configurable polling interval (default 5s); requires HeadsetControl to be installed (contributed by @segarra99)
- **Corsair K57 RGB Wireless support** — battery percentage and charging state of the keyboard through its own USB dongle (1b1c:1b62), read directly via three Bragi GET requests on the dongle's command interface (interface 1): the dongle's paired-device list first, then the keyboard's battery level and battery status, so the keyboard is never asked while it is not linked. Every reply must start with the child index of the asked address (0x00 from the dongle, 0x01 from the keyboard, as the dongle sends it) or with the address itself, and carry the GET command, a success status and a valid value before anything is decoded. Only GET is ever sent: no setting is written and software mode is never entered (contributed by @Lukk17)
- **Update checks** — BatteryWatch asks the GitHub releases API for the latest version at startup and then once a day, and can show "(Update available)" in the tray tooltip plus a dismissible download pill in the popup header. A new Updates settings page turns the check off and controls each hint; dismissing the pill hides it until a newer version appears

### Changed
- **Providers fill each other's gaps** — a device reported by two providers is one entry: the higher-priority reading stays, and the later provider fills what it left missing — a percentage it does not have, or the charging state it cannot know. A permission-blocked entry is replaced as soon as another provider reads the device
- **Bluetooth devices UPower reports without a serial are now identified by their MAC** — the identity BlueZ and Solaar report them under, so the same device merges into one entry instead of two. A device hidden under its old path-based identity might reappear and would need hiding again due to this change
- **Solaar discovered however it was installed** — the helper re-executes into whichever Python carries Solaar's library (distro/pip/pipx/conda/NixOS/venv), hands off to a Flatpak Solaar's own sandbox, caches the proven-good runner between polls, and explains what it tried when Solaar is missing. Confirmed on a Flathub-installed Solaar 1.1.20 (system scope) — the setup that previously failed — where the keyboard, mouse and headset that UPower never reported finally appeared once the hidraw rule was copied (issue #2)
- **HID udev rules grant access to the battery interface only** — a device whose battery sits on one interface (Keychron M5, ROG Azoth, Steam Controller 2) now gets a rule that matches that interface number, so its typing and other interfaces keep their default permissions. The rule file imports the USB interface number itself, because systemd before v258 does not set it for hidraw nodes. The "Copy command" now re-triggers only hidraw devices instead of every device on the system. A rule file installed by an earlier version keeps working and is not rewritten (contributed by @Lukk17)
- **`main.qml` split into components, with shared logic moved to `DeviceUtils.js`** — no behaviour change. The popup row (`DeviceRow.qml`), update pill (`UpdatePill.qml`) and tray item (`TrayDeviceItem.qml`) are their own components; providers register by being declared inside `ProviderRegistry`, in priority order; device merging, tray-item building, low-battery alert selection and the debug test devices live in plain JS, covered by unit tests. A new `validateDevice` check runs over the debug devices and the output of every provider with test fixtures, so a provider that stops filling a required field fails the tests

### Fixed
- **Logitech G502 Lightspeed shown as a keyboard** — UPower reported the mouse as a keyboard because its HID++ interface advertises the G-keys as a keyboard collection; it is now mapped to mouse, like the other Logitech mice (contributed by @ballofmatts)

### Contributors
- @birrkan — BlueZ integration (initial BluezQt implementation, reworked to bluetoothctl during review)
- @CorneliusKluge — issue #2: tireless on-device testing across many builds, from the first hidraw diagnostics to confirming the Flatpak discovery on his Flathub setup; his detailed reports and patience shaped this whole integration — thank you!
- @YourM4jesty — low-battery notifications (threshold setting, per-device toggle, and muted devices list persistence)
- @Quintisimo — Glorious wireless mouse support, with protocol implementation and testing on a Model O Wireless (PR #46)
- @ballofmatts — G502 Lightspeed device-type fix
- @segarra99 — HeadsetControl integration
- @Lukk17 — Corsair K57 RGB Wireless dongle support and scoped HID udev rules

## [0.3.2] - 2026-10-05

### Added
- **UPower can be switched off** — a new "UPower Integration" switch, first in the integrations list, stops the UPower provider completely: its polling stops and its devices are dropped, so the remaining integrations are the only source for anything the system also reports through UPower. That is the quickest way to see what one integration reports on its own - with UPower on, a Logitech mouse that UPower sees first wins the merge and Solaar's own reading is never shown. UPower polls on a fixed cadence that is not configurable, and the config page now shows it: the device list every 2s, each device's details every 10s
- **Solaar support (experimental)** — battery percentage, charging state and device type of Logitech HID++ devices, read through [Solaar](https://github.com/pwr-Solaar/Solaar)'s own library: Unifying/Bolt/Lightspeed/Centurion receivers, wired and Bluetooth devices, and headsets. Bluetooth devices get the disconnect action even when UPower does not see them, and devices that are offline, asleep or have no battery are not shown (stateless polling, default 10s). Requires Solaar installed (distro package, pip or pipx); without it the integration stays quiet. Devices needing hidraw permission get the same lock icon + "Copy command" flow as the HID provider. Tested on an M305 and an MX Master 3 only, so other Logitech hardware may need fixes - feedback welcome, please say which model and how it is connected
- **Keychron M5 support** — new request-response HID schema (0xB3:06 request / 0xB4 reply) reads the M5's battery over the vendor interface; works both wireless (Ultra-Link 8K dongle) and wired (USB-C); correct charging decode
- **ROG Azoth support** — battery level of the ASUS ROG Azoth keyboard over wired USB, the 2.4 GHz dongle and the ROG OMNI receiver, read directly via HID request/response with per-transport report formats (contributed by @LookforFPS)
- **Razer Barracuda X Chroma support** — battery percentage and charging state of the headset, read directly via two ordered HID property requests (0x21/0x2A over the 0xFF14 vendor usage page) whose replies must fully validate before decoding; not yet supported by OpenRazer (contributed by @vermi5, protocol reverse-engineered from Synapse captures and verified on hardware)

### Changed
- **User-run udev authorization** — a device whose battery needs extra permission now shows a lock icon and a "Copy command" button; the user pastes one `sudo tee` command in a terminal on their own terms. A single rule file per device covers all its connection variants (wireless + wired)
- **Stateless HID polling** — the helper reports only a current reading each 5s poll, so charging state updates promptly and devices that stop answering (asleep, or a wired mouse's idle dongle) drop immediately instead of showing stale entries

### Fixed
- **A mouse behind a Unifying receiver stayed in the list after being switched off** — the kernel's `hidpp_battery` node stays registered for as long as the *receiver* is powered, so `upower -e` keeps listing it and nothing could tell the mouse had gone to sleep; the list kept showing it at whatever percentage was last read (0%, or the stale cached value if UPower had history). A Bluetooth mouse such as the MX Master 3 was unaffected, because switching it off disconnects it and the node disappears on its own. The detail reply is now read as the authority: a device whose battery level comes back `unknown` *and* whose percentage UPower marks `(should be ignored)` is dropped, and it comes back by itself once it wakes. Both conditions are required on purpose — UPower prints `(should be ignored)` for every HID++ battery, including healthy ones, a fully charged MX Master 3 included, so filtering on that marker alone would have hidden working devices
- **A Logitech mouse behind a Unifying receiver was listed twice** — UPower reports such a device with the kernel's `HID_UNIQ` (`f9-0d-4f-0c`) in its serial field while Solaar reports the HID++ unit serial of the very same receiver unit (`F90D4F0C`); the two providers' entries were compared literally, so one mouse showed up from each. Devices are now matched on a canonical serial, which also folds the spellings of a Bluetooth MAC (`cb:6a:b2:6c:73:47` vs `CB:6A:B2:6C:73:47`). The serial itself is untouched for display, and the hidden-device list is matched on the same canonical key, so a hidden mouse stays hidden when another provider reports it in a different spelling; a named serial such as `4066-C535` is deliberately left alone rather than folded into `4066C535`, so two unrelated devices cannot collapse into one
- **Bluetooth Logitech batteries had no disconnect action** — UPowerProvider classified Bluetooth only from the device's native-path, but for kernel `hidpp` batteries over Bluetooth the native-path is just `hidpp_battery_N` while the MAC sits in the serial field. A fully colon-separated MAC serial now marks the device as Bluetooth, restoring the disconnect button; USB-receiver/cable transports report a dash-separated uniq or a raw HID++ serial and cannot match (their classification stays wireless)
- **Appearance page does not open** — the tab came up empty instead of showing the font and colour settings (issue #52, reported by @TheSpawnMan). The font family combo box assigned to `ComboBox.currentValue`, a property Qt only made writable in 6.10, so on Qt 6.9 and older the assignment is a QML compile error and the whole page fails to load. The saved font is now selected by index instead, which works on every Qt 6
- **Choosing a font family silently reverted to "System default"** — the combo box wrote to the config whenever its value changed, including the change caused by filling its own list, so merely opening the Appearance page overwrote the saved font. The config is now written only when the user actually picks a font, a font that is no longer installed falls back to "System default" rather than leaving the combo box blank, and the selection follows the config again if the Appearance settings are reset
- **Debug output for troubleshooting** — `--debug` now logs the selected node and identity, the exact request bytes, every received packet with the reason it was rejected, and timeouts, on stderr only (stdout stays valid JSON)
- **Razer devices not detected** — the OpenRazer provider now talks to `openrazer-daemon` through `gdbus` instead of `qdbus` (issue #50). Qt6 renamed the binary to `qdbus6`, so on systems that don't ship the Qt5 `qdbus` (Fedora, NixOS, Arch/CachyOS without `qt5-tools`) every call failed and the widget showed no Razer devices at all. `gdbus` ships with glib2, which Plasma already depends on, and needs no Qt startup per call
- **OpenRazer failures are no longer silent** — a failing D-Bus call is reported in the Plasma log (`BatteryWatch: OpenRazer daemon unavailable (...)`) and no longer looks identical to "no Razer devices connected"
- **KDE Connect names containing an apostrophe** — the hand-rolled D-Bus regexes skipped such values entirely, so a device named e.g. `Bob's Phone` stayed nameless and a matching id was dropped from the device list; Razer and KDE Connect now share one GVariant parser
- **An unreadable D-Bus reply no longer empties the device list** — a call that succeeded but returned something the old helpers could not read was indistinguishable from "no devices connected", so every device vanished from the popup and tray with nothing in the log. A reply that does not parse, or that parses to the wrong shape, is now refused and reported (`BatteryWatch: unreadable ... reply (...)`); the devices stay on screen until the next poll succeeds, and a device list that legitimately comes back empty still disconnects them
- **KDE Connect fractional battery levels are no longer ignored** — the pattern that read `charge` only matched whole numbers, so a reply such as `{'charge': <75.5>,}` matched nothing and the device silently kept its previous reading. Values are now decoded properly, which also means an escaped apostrophe in a name shows as `Bob's Phone` instead of `Bob\'s Phone`, and a reply that is unreadable or carries a value of the wrong type is reported in the Plasma log instead of being passed over in silence
- **HID headset icons** — the icon map covered only the legacy type spellings (`headset`, `headphones`) while the HID helper reports the canonical ones (`audio-headset`, `audio-headphones`), so a HID headset — the Barracuda X Chroma being the first — rendered with no icon; both spellings now map to their icons (contributed by @vermi5)
- **All-zero HID serials were shown as the serial** — a device whose only identity is an all-zero `HID_UNIQ` (the Barracuda X Chroma dongle reports `0000000000000000`) displayed that string as its serial, even though every unit of the model reports the same one, so identical dongles could not be told apart either; an all-zero `HID_UNIQ` is now treated as missing and the device falls back to its physical path, exactly like a device that reports no serial (contributed by @vermi5)

### Contributors
- @MrAdrianPl — reverse-engineered the Keychron M5 battery protocol (hid report probing)
- @StarPepe — on-device testing and verification of the M5 support
- @LookforFPS — ROG Azoth battery support (wired USB, 2.4 GHz dongle and OMNI receiver), reverse-engineered on hardware
- @vermi5 — Razer Barracuda X Chroma battery support: protocol reverse-engineered from Synapse captures and verified on hardware; HID headset icon and all-zero serial fixes
- @CorneliusKluge — issue #2 on-device diagnostics: the hidraw report descriptor that identified the G733's long-report response as the cause of the missing battery reading
- @TheSpawnMan — issue #52 report of the blank Appearance page (Qt 6.8.2)

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

[Unreleased]: https://github.com/itayavra/batterywatch/compare/v0.3.2...HEAD
[0.3.2]: https://github.com/itayavra/batterywatch/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/itayavra/batterywatch/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/itayavra/batterywatch/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/itayavra/batterywatch/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/itayavra/batterywatch/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/itayavra/batterywatch/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/itayavra/batterywatch/releases/tag/v0.1.0
