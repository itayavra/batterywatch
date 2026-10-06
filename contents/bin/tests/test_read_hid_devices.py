#!/usr/bin/env python3
"""
test_read_hid_devices.py - self-check for the HID helper WITHOUT hardware.

Runs the real contents/bin/read_hid_devices script against fully simulated
sysfs + hidraw devices and verifies every behavior the widget depends on:

  M5 (Keychron):  request bytes, interface-4 targeting, battery decode,
                  charging decode, wired d048, no-reply handling (device
                  dropped, stateless per run), blocked reporting, dynamic
                  udev rule generation.
  Azoth (ROG):    Wired, standard 2.4 GHz, and OMNI request-response
                  transports; their control-interface targeting, battery and
                  charging-state decode, blocked reporting, and udev rules.
  Barracuda X Chroma (Razer): ordered battery + charging requests, strict
                  reply correlation/validation, captured-packet decoding.
  SC2 (stream):   battery decode from stream report, charging state, no write.

Written as plain pytest-style test_*() functions so they read like idiomatic
Python tests. They run under pytest directly (pytest collects test_* in this
file) AND standalone via the tiny runner at the bottom, so no dependencies
are needed.

Run:  python3 contents/bin/tests/test_read_hid_devices.py
  or: pytest contents/bin/tests/test_read_hid_devices.py
Exit: 0 = all checks passed, 1 = at least one failed.
"""

import builtins
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import py_compile
import select
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, ".."))
HELPER = os.path.join(BIN, "read_hid_devices")

# Capture the real os functions BEFORE patch_module() replaces os.listdir etc. on the
# shared os module (rhd.os IS this os module), so the real subprocess run keeps working.
real_listdir = os.listdir
real_osopen = os.open
real_oswrite = os.write
real_osread = os.read
real_osclose = os.close
real_poll = select.poll


def load_helper():
    # Load the real contents/bin/read_hid_devices script as module "rhd", so
    # the tests exercise the same code the widget runs. The file has no .py
    # suffix, so the loader is specified explicitly.
    loader = importlib.machinery.SourceFileLoader("rhd", HELPER)
    spec = importlib.util.spec_from_loader("rhd", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rhd"] = mod
    loader.exec_module(mod)
    return mod


rhd = load_helper()
unpatched_usb_serial = rhd.usb_serial

# ══════════════════════════════════════════════════════════════════════════
# Scenario fakes: swap these globals between the M5, SC2, and Azoth scenarios
# ══════════════════════════════════════════════════════════════════════════
scenario = {"uevents": {}, "fake_devs": {}, "reply_fd": None, "reply_buf": bytearray(64),
            "reply_queue": [], "writes": [], "write_data": [], "reads": [], "read_sizes": [],
            "open_flags": [], "descriptors": {}, "descriptor_reads": 0}

RAZER_BATTERY_REQUEST = bytes.fromhex(
    "02 00 60 00 00 00 04 00 00 80 21 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 c7 00"
)
RAZER_BATTERY_REPLY = bytes.fromhex(
    "02 02 60 00 00 00 05 00 80 80 21 01 01 64 00 00 00 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 22 00"
)
RAZER_CHARGING_REQUEST = bytes.fromhex(
    "02 00 60 00 00 00 04 00 00 80 2a 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 cc 00"
)
RAZER_CHARGING_REPLY = bytes.fromhex(
    "02 02 60 00 00 00 05 00 80 80 2a 01 01 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 4d 00"
)

def m5_uevent(node, pid="0000D028", name="Keychron Keychron Ultra-Link 8K", iface=4):
    return (f"DRIVER=hid-generic\nHID_ID=0003:00003434:{pid}\n"
            f"HID_NAME={name}\nHID_PHYS=usb-0000:00:14.0-11/input{iface}\nHID_UNIQ=\n")

def azoth_uevent(node, pid="00001ACE", iface=1):
    return (f"DRIVER=hid-generic\nHID_ID=0003:00000B05:{pid}\n"
            f"HID_NAME=ROG Azoth\nHID_PHYS=usb-0000:00:14.0-12/input{iface}\n"
            "HID_UNIQ=SN1LAZOTG6C2\n")

def fake_open(path, mode="r", *a, **k):
    if path.startswith("/sys/class/hidraw"):
        node = path.split("/")[4]
        if path.endswith("report_descriptor"):
            scenario["descriptor_reads"] += 1
            desc = scenario["descriptors"].get(node)
            if desc is None:      # node present but its descriptor unreadable
                raise OSError(5, "Input/output error")
            return io.BytesIO(desc)
        return io.StringIO(scenario["uevents"][node])
    return builtins.open(path, mode, *a, **k)

def fake_osopen(path, flags):
    scenario["open_flags"].append(flags)
    if scenario.get("deny") and path in scenario["fake_devs"]:
        raise PermissionError(13, "Permission denied")
    if path in scenario["fake_devs"]:
        return scenario["fake_devs"][path]
    raise FileNotFoundError(2, "no such file")

def fake_write(fd, data):
    scenario["writes"].append(fd)
    scenario["write_data"].append(bytes(data))
    return len(data)

def fake_read(fd, size):
    scenario["reads"].append(fd)
    scenario["read_sizes"].append(size)
    if fd == scenario["reply_fd"]:
        if scenario["reply_queue"]:
            return bytes(scenario["reply_queue"].pop(0))
        return bytes(scenario["reply_buf"])
    return b""

class FakePoller:
    def __init__(self):
        self.reg = []
    def register(self, fd, ev):
        self.reg.append(fd)
    def unregister(self, fd):
        if fd in self.reg:
            self.reg.remove(fd)
    def poll(self, timeout_ms):
        for fd in self.reg:
            if fd == scenario["reply_fd"]:
                # pending data only: a queued sequence, or the standing reply buffer
                if scenario["reply_queue"] or scenario["reply_buf"]:
                    return [(fd, select.POLLIN)]
        return []

def install_m5_scenario(pid="0000D028", name="Keychron Keychron Ultra-Link 8K", with_blocked=False):
    scenario["uevents"] = {
        "hidraw3": m5_uevent("hidraw3", pid, name, 0),
        "hidraw4": m5_uevent("hidraw4", pid, name, 1),
        "hidraw5": m5_uevent("hidraw5", pid, name, 2),
        "hidraw6": m5_uevent("hidraw6", pid, name, 4),
    }
    scenario["fake_devs"] = {f"/dev/{k}": 300 + int(k[-1]) for k in scenario["uevents"]}
    scenario["deny"] = with_blocked
    scenario["writes"] = []
    scenario["write_data"] = []
    scenario["reads"] = []
    scenario["read_sizes"] = []
    scenario["open_flags"] = []
    scenario["descriptors"] = {}
    scenario["descriptor_reads"] = 0
    scenario["reply_buf"] = bytearray(64)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 306

def install_sc2_scenario():
    scenario["uevents"] = {
        "hidraw7": "DRIVER=hid-generic\nHID_ID=0003:000028DE:00001304\n"
                   "HID_NAME=Steam Controller 2\n"
                   "HID_PHYS=usb-0000:00:14.0-7/input2\nHID_UNIQ=\n",
    }
    scenario["fake_devs"] = {"/dev/hidraw7": 207}
    scenario["deny"] = False
    scenario["writes"] = []
    scenario["write_data"] = []
    scenario["reads"] = []
    scenario["read_sizes"] = []
    scenario["open_flags"] = []
    scenario["descriptors"] = {}
    scenario["descriptor_reads"] = 0
    scenario["reply_buf"] = bytearray(16)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 207

def install_azoth_scenario(pid="00001ACE", with_blocked=False):
    scenario["uevents"] = {
        "hidraw7": azoth_uevent("hidraw7", pid, 0),
        "hidraw8": azoth_uevent("hidraw8", pid, 1),
        "hidraw9": azoth_uevent("hidraw9", pid, 2),
    }
    scenario["fake_devs"] = {f"/dev/{key}": 300 + int(key[-1]) for key in scenario["uevents"]}
    scenario["deny"] = with_blocked
    scenario["writes"] = []
    scenario["write_data"] = []
    scenario["reads"] = []
    scenario["read_sizes"] = []
    scenario["open_flags"] = []
    scenario["descriptors"] = {}
    scenario["descriptor_reads"] = 0
    scenario["reply_buf"] = bytearray(65)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 309 if pid == "00001ACE" else 308

# ── Synthetic vendor-usage-page device ──────────────────────────────────────
# Stands in for the device families that put the battery collection on a vendor
# page (Glorious mice and friends): which interface carries it cannot be told
# from the interface number, so the report descriptor decides.
_TEST_PID = 0xDEAD
_TEST_VID = 0xBEEF

def hid_descriptor(usage_page=0xFF01):
    # minimal HID report descriptor declaring one usage page + a 2-byte usage
    page_item = (bytes([0x05, usage_page]) if usage_page <= 0xFF
                 else bytes([0x06, usage_page & 0xFF, (usage_page >> 8) & 0xFF]))
    return page_item + bytes([0x0A, 0x02, 0x02]) + b"\xC0"

def install_vendor_scenario(usage_page=0xFF01, iface=3, with_blocked=False):
    scenario["uevents"] = {
        "hidraw8": (f"DRIVER=hid-generic\nHID_ID=0003:{_TEST_VID:08X}:{_TEST_PID:08X}\n"
                    f"HID_NAME=Test Vendor Mouse\n"
                    f"HID_PHYS=usb-0000:00:14.0-11/input{iface}\nHID_UNIQ=\n"),
    }
    scenario["fake_devs"] = {"/dev/hidraw8": 208}
    scenario["deny"] = with_blocked
    scenario["writes"] = []
    scenario["write_data"] = []
    scenario["reads"] = []
    scenario["read_sizes"] = []
    scenario["open_flags"] = []
    scenario["descriptors"] = ({"hidraw8": hid_descriptor(usage_page)}
                               if usage_page is not None else {})
    scenario["descriptor_reads"] = 0
    scenario["reply_buf"] = bytearray(16)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 208

@contextlib.contextmanager
def vendor_device(usage_page=rhd.VENDOR_USAGE_PAGE, pid=_TEST_PID, vid=_TEST_VID):
    """Registers a throwaway device whose node is selected by usage page."""
    dev = rhd.Device(
        name="Test Vendor Mouse",
        device_type=rhd.DeviceType.MOUSE,
        vid=vid,
        variants=(rhd.DeviceVariant(pid, None, usage_page),),
        source=rhd.InputStreamSchema(
            charge=rhd.DataPos(0x43, 2),
            charge_range=None,
            status=rhd.ChargingStates(pos=rhd.DataPos(0x43, 1), states={0x01: False, 0x02: True}),
        ),
        parse=None,
    )
    rhd.KNOWN_DEVICES.append(dev)
    # _USAGE_PAGE_PIDS is derived from the registry, so refresh it for the test
    rhd._USAGE_PAGE_PIDS.add(pid)
    try:
        yield dev
    finally:
        rhd.KNOWN_DEVICES.remove(dev)
        rhd._USAGE_PAGE_PIDS.discard(pid)

def install_razer_scenario(with_blocked=False, usage_page=0xFF14):
    scenario["uevents"] = {
        "hidraw5": ("DRIVER=hid-generic\nHID_ID=0003:00001532:00000574\n"
                    "HID_NAME=MediaTek Inc Razer Barracuda X Chroma\n"
                    "HID_PHYS=usb-0000:00:14.0-6.1.2/input3\n"
                    "HID_UNIQ=0000000000000000\n"),
    }
    scenario["fake_devs"] = {"/dev/hidraw5": 205}
    scenario["deny"] = with_blocked
    scenario["writes"] = []
    scenario["write_data"] = []
    scenario["reads"] = []
    scenario["read_sizes"] = []
    scenario["open_flags"] = []
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [RAZER_BATTERY_REPLY, RAZER_CHARGING_REPLY]
    scenario["reply_fd"] = 205
    scenario["descriptors"] = ({"hidraw5": hid_descriptor(usage_page)}
                               if usage_page is not None else {})
    scenario["descriptor_reads"] = 0

def set_m5_reply(byte20=87, report_id=0xB4, cmd=0x06):
    buf = bytearray(64)
    buf[0] = report_id
    buf[1] = cmd
    buf[20] = byte20
    scenario["reply_buf"] = buf

def set_m5_reply_hex(hexstr):
    raw = bytes.fromhex(hexstr.replace(" ", ""))
    scenario["reply_buf"] = bytearray(raw.ljust(64, b"\x00")[:64])

def set_sc2_report(state=0x02, pct=85):
    buf = bytearray(16)
    buf[0] = 0x43
    buf[1] = state
    buf[2] = pct
    scenario["reply_buf"] = buf

def set_azoth_reply(pct=73, state=0x00, prefix=bytes.fromhex("021201")):
    buf = bytearray(64 if prefix[0] in (0x02, 0x12) else 65)
    buf[:len(prefix)] = prefix
    battery_offset = 5 if prefix[0] == 0x12 else 6
    status_offset = 8 if prefix[0] == 0x12 else 9
    buf[battery_offset] = pct
    buf[status_offset] = state
    scenario["reply_buf"] = buf

def patch_module():
    rhd.open = fake_open
    # Scenario fixtures provide only hidraw uevent files.  Do not let their
    # parse_uevent() calls walk the host's real sysfs parent hierarchy.
    rhd.usb_serial = lambda path, vid, pid: None
    rhd.os.open = fake_osopen
    rhd.os.listdir = lambda *a: list(scenario["uevents"].keys())
    rhd.os.write = fake_write
    rhd.os.read = fake_read
    rhd.os.close = lambda fd: None
    rhd.select.poll = FakePoller

def run_main_capture():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            rhd.main()
        except SystemExit:
            pass
    return out.getvalue().strip()

@contextlib.contextmanager
def sandboxed_rules():
    # Point the generated-rule dir somewhere writable (real dir is /etc/udev/rules.d)
    rules_dir = tempfile.mkdtemp()
    orig = rhd.UDEV_RULES_DIR
    rhd.UDEV_RULES_DIR = rules_dir
    try:
        yield rules_dir
    finally:
        rhd.UDEV_RULES_DIR = orig

@contextlib.contextmanager
def simulate_env():
    # --simulate reads rule files from UDEV_RULES_DIR and sys.argv
    sim_dir = tempfile.mkdtemp()
    orig_rules = rhd.UDEV_RULES_DIR
    saved_argv = sys.argv
    rhd.UDEV_RULES_DIR = sim_dir
    sys.argv = ["read_hid_devices", "--simulate"]
    try:
        yield sim_dir
    finally:
        sys.argv = saved_argv
        rhd.UDEV_RULES_DIR = orig_rules

# Prime the tempdir cache BEFORE patch_module() replaces os.open: the first
# tempfile.mkdtemp() call probes /tmp via os.open(path, flags, 0o600), which
# the fake would reject (2-arg signature).
tempfile.gettempdir()
patch_module()


# ══════════════════════════════════════════════════════════════════════════
# Schema / reference behavior
# ══════════════════════════════════════════════════════════════════════════
def test_usb_serial_is_preferred_over_malformed_hid_uniq():
    root = tempfile.mkdtemp()
    hid_dir = os.path.join(root, "usb", "1-3", "1-3:1.1", "hid")
    usb_dir = os.path.dirname(os.path.dirname(hid_dir))
    os.makedirs(hid_dir)
    for name, value in (("idVendor", "0b05\n"), ("idProduct", "1a83\n"),
                        ("serial", "SN1LAZOTG6C2\n")):
        with open(os.path.join(usb_dir, name), "w") as file:
            file.write(value)
    assert unpatched_usb_serial(os.path.join(hid_dir, "uevent"), 0x0B05, 0x1A83) == "SN1LAZOTG6C2"

def test_azoth_resolver_prefers_sanitized_usb_parent_serial():
    root = tempfile.mkdtemp()
    hid_dir = os.path.join(root, "usb", "1-3", "1-3:1.1", "hid")
    usb_dir = os.path.dirname(os.path.dirname(hid_dir))
    os.makedirs(hid_dir)
    for name, value in (("idVendor", "0b05\n"), ("idProduct", "1a83\n"),
                        ("serial", "SN1LAZOTG6C2\x18\xbe\n")):
        with open(os.path.join(usb_dir, name), "w") as file:
            file.write(value)
    saved_usb_serial = rhd.usb_serial
    rhd.usb_serial = unpatched_usb_serial
    try:
        serial = rhd._azoth_serial_resolver(
            os.path.join(hid_dir, "uevent"), 0x0B05, 0x1A83,
            {"HID_UNIQ": "should-not-win"},
        )
    finally:
        rhd.usb_serial = saved_usb_serial
    assert serial == "SN1LAZOTG6C2"

def test_azoth_resolver_truncates_invalid_hid_uniq():
    assert rhd._azoth_serial_resolver(
        "unused", 0x0B05, 0x1A83, {"HID_UNIQ": "SN1LAZOTG6C2\x18\xbe"}
    ) == "SN1LAZOTG6C2"

def test_azoth_resolver_keeps_clean_hid_uniq_byte_exact():
    assert rhd._azoth_serial_resolver(
        "unused", 0x0B05, 0x1A83, {"HID_UNIQ": "SN1LAZOTG6C2"}
    ) == "SN1LAZOTG6C2"

def test_non_azoth_hid_uniq_is_not_resolved_or_sanitized():
    install_m5_scenario()
    scenario["uevents"]["hidraw6"] = m5_uevent("hidraw6")[:-1] + "serial\x18\xbe\n"
    assert rhd.find_devices()[0].serial == "serial\x18\xbe"

def test_missing_hid_uniq_exposes_the_physical_identity():
    install_m5_scenario()
    set_m5_reply(87)
    entry = rhd._device_entry(rhd.find_devices()[0])
    assert entry["serial"] == "usb-0000:00:14.0-11"

def test_meaningful_hid_uniq_remains_displayable():
    install_m5_scenario()
    set_m5_reply(87)
    scenario["uevents"]["hidraw6"] = m5_uevent("hidraw6")[:-1] + "SN000123\n"
    entry = rhd._device_entry(rhd.find_devices()[0])
    assert entry["serial"] == "SN000123"

def test_reference_match():
    # Reference match (github.com/itayavra/batterywatch/issues/5)
    dev = rhd.KNOWN_DEVICES[0]
    assert dev.source.request == bytes.fromhex("b306") + b"\x00" * 62
    assert dev.source.timeout == 1, "request timeout (reference read 128, 1000ms)"
    assert dev.source.charge == rhd.DataPos(0xB4, 20), "battery byte offset (reference data_array[20])"
    assert dev.variants == (rhd.DeviceVariant(0xD028, 4), rhd.DeviceVariant(0xD048, 4))

def test_azoth_reference_profile():
    azoths = [dev for dev in rhd.KNOWN_DEVICES if dev.name == "ROG Azoth"]
    assert len(azoths) == 1, "all Azoth transports belong to one device definition"
    dev = azoths[0]
    assert dev.device_type == rhd.DeviceType.KEYBOARD
    wired, wireless = dev.variants[:2]
    assert (wired.pid, wired.iface) == (0x1A83, 1)
    assert wired.source.request == bytes.fromhex("1201") + b"\x00" * 62
    assert wired.source.reply_prefix == bytes.fromhex("1201")
    assert wired.source.charge == rhd.DataPos(0x12, 5)
    assert wired.source.status == rhd.ChargingStates(rhd.DataPos(0x12, 8), {0x01: True})
    assert wireless == rhd.DeviceVariant(0x1A85, 1)
    assert dev.source.request == bytes.fromhex("001201") + b"\x00" * 62
    assert dev.source.reply_prefix == bytes.fromhex("001201")
    assert dev.source.charge == rhd.DataPos(0x00, 6)
    assert dev.source.status == rhd.ChargingStates(rhd.DataPos(0x00, 9), {0x01: True})

def test_azoth_omni_reference_profile():
    dev = next(dev for dev in rhd.KNOWN_DEVICES if dev.name == "ROG Azoth")
    omni = dev.variants[2]
    assert (omni.pid, omni.iface) == (0x1ACE, 2)
    assert omni.source.request == bytes.fromhex("021201") + b"\x00" * 61
    assert omni.source.reply_prefix == bytes.fromhex("021201")
    assert omni.source.charge == rhd.DataPos(0x02, 6)
    assert omni.source.status == rhd.ChargingStates(rhd.DataPos(0x02, 9), {0x01: True})


# ══════════════════════════════════════════════════════════════════════════
# Real hardware captures (StarPepe, all 3 states)
# ══════════════════════════════════════════════════════════════════════════
def test_real_capture_wireless_6_percent():
    install_m5_scenario()
    set_m5_reply_hex("b4 06 00 02 02 02 90 01 20 03 40 06 80 0c 88 13 15 05 04 0a 06"
                     " 00 00 00 00 00 00 b7 00 00 00 04 04 04 04 04 04 04 04 04 04"
                     " 00 00 00 00 01 02 03 04 05 06 05 00 00 00 00 00 00 00 00 00 00 00 00")
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 6, "charging": False}

def test_real_capture_charging_ext_charger():
    install_m5_scenario()
    set_m5_reply_hex("b4 06 00 02 02 02 90 01 20 03 40 06 80 0c 88 13 15 05 04 0a 87"
                     " 00 00 00 00 00 00 b7 00 00 00 04 04 04 04 04 04 04 04 04 04"
                     " 00 00 00 00 01 02 03 04 05 06 05 00 00 00 00 00 00 00 00 00 00 00 00")
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 7, "charging": True}

def test_real_capture_wired_d048():
    install_m5_scenario(pid="0000D048", name="Keychron M5")
    set_m5_reply_hex("b4 06 00 02 02 02 90 01 20 03 40 06 80 0c 88 13 15 05 04 0a 89"
                     " 00 00 00 00 00 00 b7 00 00 00 04 04 04 04 04 04 04 04 04 04"
                     " 00 00 00 00 01 02 03 04 05 06 05 00 00 00 00 00 00 00 00 00 00 00 00")
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 9, "charging": True}


# ══════════════════════════════════════════════════════════════════════════
# M5: discovery (interface-4 targeting)
# ══════════════════════════════════════════════════════════════════════════
def test_discovery_targets_interface_4_only():
    install_m5_scenario()
    devs = rhd.find_devices()
    assert [d.devpath for d in devs] == ["/dev/hidraw6"], f"found: {[d.devpath for d in devs]!r}"
    assert devs[0].serial == "usb-0000:00:14.0-11", "serial falls back to the physical path"
    assert devs[0].pid == 0xD028, "matched pid recorded"

def test_discovery_no_interface_4_node_matches_nothing():
    install_m5_scenario()
    scenario["uevents"]["hidraw6"] = m5_uevent("hidraw6", iface=5)
    assert rhd.find_devices() == []

def test_discovery_two_dongles_are_distinct():
    install_m5_scenario()
    scenario["uevents"]["hidraw9"] = m5_uevent("hidraw9").replace("00:14.0-11", "00:14.0-12")
    scenario["fake_devs"] = {f"/dev/{k}": 300 + int(k[-1]) for k in scenario["uevents"]}
    devs = rhd.find_devices()
    assert sorted(d.serial for d in devs) == ["usb-0000:00:14.0-11", "usb-0000:00:14.0-12"], \
        f"serials: {[d.serial for d in devs]!r}"


# ══════════════════════════════════════════════════════════════════════════
# M5: battery read (request + 0xB4 reply)
# ══════════════════════════════════════════════════════════════════════════
def test_m5_discharging_87():
    install_m5_scenario()
    set_m5_reply(byte20=87)
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 87, "charging": False}
    assert scenario["writes"] == [306], f"request written exactly once to vendor iface: {scenario['writes']!r}"

def test_m5_charging_decode():
    install_m5_scenario()
    set_m5_reply(byte20=135)
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 7, "charging": True}, "0x80 flag + level 7"

def test_m5_charging_level_clamped_to_100():
    install_m5_scenario()
    set_m5_reply(byte20=240)
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 100, "charging": True}, "raw 240 -> 112 clamped"

def test_m5_wrong_report_id_rejected():
    install_m5_scenario()
    set_m5_reply(report_id=0xB3, byte20=87)
    assert rhd.read_status(rhd.find_devices()[0]) is None

def test_m5_bad_command_echo_rejected():
    install_m5_scenario()
    set_m5_reply(cmd=0x00, byte20=87)
    assert rhd.read_status(rhd.find_devices()[0]) is None


# ══════════════════════════════════════════════════════════════════════════
# M5: stateless - a dead device drops, then re-reads live on the next run
# ══════════════════════════════════════════════════════════════════════════
def test_m5_stateless_dead_device_drops_then_recovers():
    install_m5_scenario()
    set_m5_reply(byte20=87)
    d = rhd.find_devices()[0]
    assert rhd.read_status(d) == {"percentage": 87, "charging": False}

    # Dead link (mouse wired elsewhere): the node is still enumerated but never
    # answers. Stateless helper reports None -> the widget drops the entry.
    scenario["reply_fd"] = None
    scenario["writes"].clear()
    assert rhd.read_status(d) is None
    assert scenario["writes"] == [306], f"request still written once: {scenario['writes']!r}"

    scenario["reply_fd"] = 306
    assert rhd.read_status(d) == {"percentage": 87, "charging": False}, "next run re-reads hardware (no stale cache)"


# ══════════════════════════════════════════════════════════════════════════
# M5: wired mode (d048)
# ══════════════════════════════════════════════════════════════════════════
def test_wired_d048_found_and_decoded():
    install_m5_scenario(pid="0000D048", name="Keychron M5")
    set_m5_reply(byte20=130)
    devs = rhd.find_devices()
    assert [d.devpath for d in devs] == ["/dev/hidraw6"], f"found: {[d.devpath for d in devs]!r}"
    assert rhd.read_status(devs[0]) == {"percentage": 2, "charging": True}, "byte20=130 -> 2%"


# ══════════════════════════════════════════════════════════════════════════
# ROG Azoth: wired, standard 2.4 GHz, and OMNI request-response transports
# ══════════════════════════════════════════════════════════════════════════
def test_azoth_discovery_targets_control_interface_only():
    install_azoth_scenario()
    devs = rhd.find_devices()
    assert [dev.devpath for dev in devs] == ["/dev/hidraw9"]
    assert devs[0].serial == "SN1LAZOTG6C2"
    assert devs[0].pid == 0x1ACE

def test_azoth_wired_and_wireless_variants_are_found():
    for pid, prefix in (("00001A83", bytes.fromhex("1201")),
                        ("00001A85", bytes.fromhex("001201"))):
        install_azoth_scenario(pid=pid)
        set_azoth_reply(prefix=prefix)
        devs = rhd.find_devices()
        assert len(devs) == 1
        assert rhd.read_status(devs[0]) == {"percentage": 73, "charging": False}

def test_azoth_wired_request_uses_64_byte_unprefixed_report():
    install_azoth_scenario(pid="00001A83")
    set_azoth_reply(prefix=bytes.fromhex("1201"))
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 73, "charging": False}
    assert scenario["writes"] == [308]
    assert scenario["write_data"] == [bytes.fromhex("1201") + b"\x00" * 62]
    assert scenario["read_sizes"] == [64]

def test_azoth_wireless_request_is_one_padded_65_byte_report():
    install_azoth_scenario(pid="00001A85")
    set_azoth_reply(prefix=bytes.fromhex("001201"))
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 73, "charging": False}
    assert scenario["writes"] == [308]
    assert scenario["write_data"] == [bytes.fromhex("001201") + b"\x00" * 62]
    assert scenario["read_sizes"] == [65]

def test_azoth_omni_request_uses_vendor_report_id_and_64_bytes():
    install_azoth_scenario()
    set_azoth_reply()
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 73, "charging": False}
    assert scenario["writes"] == [309]
    assert scenario["write_data"] == [bytes.fromhex("021201") + b"\x00" * 61]
    assert scenario["read_sizes"] == [64]

def test_azoth_decodes_percentage_and_charging_states():
    for pct, state, charging in ((0, 0, False), (50, 1, True), (100, 2, False)):
        install_azoth_scenario()
        set_azoth_reply(pct=pct, state=state)
        assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": pct, "charging": charging}

def test_azoth_invalid_echo_and_timeout_emit_no_status():
    install_azoth_scenario()
    set_azoth_reply(prefix=bytes.fromhex("021200"))
    assert rhd.read_status(rhd.find_devices()[0]) is None

    install_azoth_scenario()
    set_azoth_reply(prefix=bytes.fromhex("011201"))
    assert rhd.read_status(rhd.find_devices()[0]) is None

    install_azoth_scenario()
    scenario["reply_fd"] = None
    assert rhd.read_status(rhd.find_devices()[0]) is None

def test_azoth_blocked_entry_and_udev_rule_cover_both_variants():
    install_azoth_scenario(with_blocked=True)
    dev = rhd.find_devices()[0]
    assert rhd.is_blocked(dev) is True
    entry = rhd._device_entry(dev)
    assert entry["blocked"] is True
    assert entry["unblock_command"] == rhd.udev_unblock_command(0x0B05)

    rule = rhd.udev_rule_for(0x0B05)
    assert 'ATTRS{idProduct}=="1a83"' in rule
    assert 'ATTRS{idProduct}=="1a85"' in rule
    assert 'ATTRS{idProduct}=="1ace"' in rule
    assert rule.count('MODE="0660"') == 3


# ══════════════════════════════════════════════════════════════════════════
# Razer Barracuda X Chroma: ordered property requests on report 0x02
# ══════════════════════════════════════════════════════════════════════════
def test_razer_profile_uses_the_exact_captured_requests():
    dev = next(dev for dev in rhd.KNOWN_DEVICES
               if dev.name == "Razer Barracuda X Chroma")
    assert dev.device_type == rhd.DeviceType.HEADSET
    assert dev.variants == (rhd.DeviceVariant(0x0574, None, 0xFF14),)
    assert [transaction.key for transaction in dev.source.transactions] == [
        "battery", "charging"
    ]
    assert [transaction.request for transaction in dev.source.transactions] == [
        RAZER_BATTERY_REQUEST, RAZER_CHARGING_REQUEST
    ]

def test_razer_real_captures_decode_after_two_ordered_requests():
    install_razer_scenario()
    dev = rhd.find_devices()[0]
    assert rhd.read_status(dev) == {"percentage": 100, "charging": False}
    assert scenario["write_data"] == [RAZER_BATTERY_REQUEST, RAZER_CHARGING_REQUEST]
    assert scenario["read_sizes"] == [64, 64]

def test_transactions_can_omit_the_single_request_without_an_extra_write():
    install_razer_scenario()
    dev = rhd.find_devices()[0]
    schema = rhd.RequestSchema(
        charge=rhd.DataPos(0x02, 13),
        charge_range=None,
        status=None,
        transactions=dev.source.transactions,
    )
    assert rhd.read_status(dev._replace(source=schema)) == {
        "percentage": 100, "charging": False
    }
    assert scenario["write_data"] == [RAZER_BATTERY_REQUEST, RAZER_CHARGING_REQUEST]

def test_razer_all_zero_hid_uniq_uses_existing_physical_path_fallback():
    install_razer_scenario()
    entry = rhd._device_entry(rhd.find_devices()[0])
    assert entry["serial"] == "usb-0000:00:14.0-6.1.2"

def test_razer_correlates_same_report_id_by_echoed_property():
    install_razer_scenario()
    scenario["reply_queue"] = [
        RAZER_CHARGING_REPLY,  # report 0x02, but not the requested property 0x21
        RAZER_BATTERY_REPLY,
        RAZER_CHARGING_REPLY,
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {
        "percentage": 100, "charging": False
    }
    assert len(scenario["reads"]) == 3
    assert scenario["write_data"] == [RAZER_BATTERY_REQUEST, RAZER_CHARGING_REQUEST]

def test_razer_correlates_property_reply_by_report_id_too():
    install_razer_scenario()
    wrong_report = bytearray(RAZER_BATTERY_REPLY)
    wrong_report[0] = 0x07
    scenario["reply_queue"] = [
        bytes(wrong_report), RAZER_BATTERY_REPLY, RAZER_CHARGING_REPLY
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {
        "percentage": 100, "charging": False
    }
    assert len(scenario["reads"]) == 3

def test_razer_rejects_bad_checksum_then_accepts_real_capture():
    install_razer_scenario()
    bad_checksum = bytearray(RAZER_BATTERY_REPLY)
    bad_checksum[62] ^= 0x01
    scenario["reply_queue"] = [
        bytes(bad_checksum), RAZER_BATTERY_REPLY, RAZER_CHARGING_REPLY
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {
        "percentage": 100, "charging": False
    }
    assert len(scenario["reads"]) == 3

def test_razer_rejects_truncated_and_malformed_property_replies():
    install_razer_scenario()
    bad_header = bytearray(RAZER_BATTERY_REPLY)
    bad_header[11] = 0x00
    scenario["reply_queue"] = [
        RAZER_BATTERY_REPLY[:-1], bytes(bad_header),
        RAZER_BATTERY_REPLY, RAZER_CHARGING_REPLY,
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {
        "percentage": 100, "charging": False
    }
    assert len(scenario["reads"]) == 4

def test_razer_rejects_checksum_correct_out_of_range_values():
    install_razer_scenario()
    invalid_battery = bytearray(RAZER_BATTERY_REPLY)
    invalid_battery[13] = 101
    invalid_battery[62] = 0x23
    invalid_charging = bytearray(RAZER_CHARGING_REPLY)
    invalid_charging[13] = 2
    invalid_charging[62] = 0x4F
    scenario["reply_queue"] = [
        bytes(invalid_battery), RAZER_BATTERY_REPLY,
        bytes(invalid_charging), RAZER_CHARGING_REPLY,
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {
        "percentage": 100, "charging": False
    }
    assert len(scenario["reads"]) == 4

def test_razer_charging_value_one_decodes_true():
    install_razer_scenario()
    charging = bytearray(RAZER_CHARGING_REPLY)
    charging[13] = 1
    charging[62] = 0x4C
    scenario["reply_queue"] = [RAZER_BATTERY_REPLY, bytes(charging)]
    assert rhd.read_status(rhd.find_devices()[0]) == {
        "percentage": 100, "charging": True
    }

def test_razer_second_transaction_timeout_publishes_no_partial_state():
    install_razer_scenario()
    scenario["reply_queue"] = [RAZER_BATTERY_REPLY]
    assert rhd.read_status(rhd.find_devices()[0]) is None
    assert scenario["write_data"] == [RAZER_BATTERY_REQUEST, RAZER_CHARGING_REQUEST]

def test_razer_first_transaction_timeout_does_not_send_second_request():
    install_razer_scenario()
    scenario["reply_queue"] = []
    assert rhd.read_status(rhd.find_devices()[0]) is None
    assert scenario["write_data"] == [RAZER_BATTERY_REQUEST]

def test_razer_discovery_requires_vendor_usage_page_ff14():
    install_razer_scenario()
    assert [dev.devpath for dev in rhd.find_devices()] == ["/dev/hidraw5"]

    install_razer_scenario(usage_page=0xFF13)
    assert rhd.find_devices() == []

def test_razer_blocked_entry_uses_existing_request_schema_udev_path():
    install_razer_scenario(with_blocked=True)
    dev = rhd.find_devices()[0]
    assert rhd.is_blocked(dev) is True
    entry = rhd._device_entry(dev)
    assert entry["blocked"] is True
    assert entry["vid"] == "1532"
    assert entry["pid"] == "0574"
    assert 'ATTRS{idProduct}=="0574"' in rhd.udev_rule_for(0x1532)
    assert 'MODE="0660"' in rhd.udev_rule_for(0x1532)


# ══════════════════════════════════════════════════════════════════════════
# M5: blocked (needs udev rule) reporting
# ══════════════════════════════════════════════════════════════════════════
def test_is_blocked_true_on_eacces():
    install_m5_scenario(with_blocked=True)
    assert rhd.is_blocked(rhd.find_devices()[0]) is True

def test_is_blocked_false_when_readable():
    install_m5_scenario(with_blocked=False)
    assert rhd.is_blocked(rhd.find_devices()[0]) is False

def test_is_blocked_uses_effective_variant_schema_open_mode():
    # The effective schema can differ from the registry device's default.
    # Permissions must follow FoundDevice.source, just like reading does.
    install_m5_scenario()
    stream_device = next(dev for dev in rhd.KNOWN_DEVICES
                         if dev.name == "Steam Controller 2")
    request_device = next(dev for dev in rhd.KNOWN_DEVICES
                          if dev.name == "Keychron M5")
    m5 = rhd.find_devices()[0]

    request_variant = rhd.FoundDevice(m5.devpath, m5.serial, stream_device, m5.pid, request_device.source)
    assert rhd.is_blocked(request_variant) is False
    assert scenario["open_flags"] == [os.O_RDWR | os.O_NONBLOCK]

    scenario["open_flags"] = []
    scenario["descriptors"] = {}
    scenario["descriptor_reads"] = 0
    stream_variant = rhd.FoundDevice(m5.devpath, m5.serial, request_device, m5.pid, stream_device.source)
    assert rhd.is_blocked(stream_variant) is False
    assert scenario["open_flags"] == [os.O_RDONLY | os.O_NONBLOCK]


# ══════════════════════════════════════════════════════════════════════════
# Per-device udev rule command (one rule file per device/vid)
# ══════════════════════════════════════════════════════════════════════════
def test_udev_rule_path_is_vid_wide():
    assert rhd.udev_rule_path(0x3434) == "/etc/udev/rules.d/70-batterywatch-hid-3434.rules"

def test_m5_rule_covers_both_variants():
    rule = rhd.udev_rule_for(0x3434)
    assert rule.count('ATTRS{idProduct}') == 2, "one line per variant"
    assert 'ATTRS{idProduct}=="d028"' in rule
    assert 'ATTRS{idProduct}=="d048"' in rule

def test_m5_rule_uses_write_mode():
    assert rhd.udev_rule_for(0x3434).count('MODE="0660"') == 2

def test_sc2_rule_uses_read_only_mode():
    assert rhd.udev_rule_for(0x28de).count('MODE="0440"') == 2

def test_install_udev_removed():
    # The install path was removed: the helper only emits the command, the user runs it
    assert not hasattr(rhd, "install_udev")

def test_udev_unblock_command_names_the_rule_file():
    with sandboxed_rules() as rules_dir:
        cmd = rhd.udev_unblock_command(0x3434)
        assert os.path.join(rules_dir, "70-batterywatch-hid-3434.rules") in cmd, cmd

def test_udev_unblock_command_contains_rule_and_reload():
    cmd = rhd.udev_unblock_command(0x3434)
    assert 'ATTRS{idVendor}=="3434"' in cmd
    assert "udevadm control --reload-rules" in cmd
    assert "udevadm trigger" in cmd

def test_udev_unblock_command_is_readable_heredoc():
    # Wrapped in `sudo sh -c '...'` so the same heredoc pastes in sh/bash/zsh/fish
    cmd = rhd.udev_unblock_command(0x3434)
    assert cmd.startswith("sudo sh -c 'tee ")
    assert "<<EOF" in cmd
    assert "EOF'" in cmd

def test_emitted_command_writes_one_file_covering_every_variant():
    with sandboxed_rules() as rules_dir:
        # No install path exists anymore: simulate what the user runs by
        # executing the emitted tee block ourselves.
        cmd = rhd.udev_unblock_command(0x3434)
        wrapper = cmd[:cmd.index("EOF'") + len("EOF'")]
        subprocess.run(["sh", "-c", wrapper.replace("sudo ", "")], check=True)
        with open(os.path.join(rules_dir, "70-batterywatch-hid-3434.rules")) as f:
            rule = f.read()
        assert 'ATTRS{idProduct}=="d028"' in rule
        assert 'ATTRS{idProduct}=="d048"' in rule
        assert rule.count(rhd.UDEV_HEADER) == 1

def test_udev_rule_exists_is_vid_wide():
    with sandboxed_rules() as rules_dir:
        with open(os.path.join(rules_dir, "70-batterywatch-hid-3434.rules"), "w") as f:
            f.write(rhd.UDEV_HEADER + "\n" + rhd.udev_rule_for(0x3434) + "\n")
        assert rhd._rule_exists(0x3434) is True, "any variant covered"
        assert rhd._rule_exists(0x28de) is False


# ══════════════════════════════════════════════════════════════════════════
# --simulate mode (no hardware)
# ══════════════════════════════════════════════════════════════════════════
def test_simulate_both_blocked_before_any_rule():
    with simulate_env():
        assert json.loads(run_main_capture()) == [
            {"name": "Keychron M5", "serial": "sim-keychron-m5", "blocked": True, "vid": "3434", "pid": "d028",
             "unblock_command": rhd.udev_unblock_command(0x3434), "deviceType": "mouse"},
            {"name": "Steam Controller 2", "serial": "sim-steam-controller-2", "blocked": True, "vid": "28de", "pid": "1304",
             "unblock_command": rhd.udev_unblock_command(0x28de), "deviceType": "gamepad"},
        ]

def test_simulate_m5_reports_after_its_rule():
    with simulate_env() as sim_dir:
        with open(os.path.join(sim_dir, "70-batterywatch-hid-3434.rules"), "w") as f:
            f.write(rhd.UDEV_HEADER + "\n" + rhd.udev_rule_for(0x3434) + "\n")
        assert json.loads(run_main_capture()) == [
            {"name": "Keychron M5", "serial": "sim-keychron-m5", "percentage": 88, "charging": False, "deviceType": "mouse"},
            {"name": "Steam Controller 2", "serial": "sim-steam-controller-2", "blocked": True, "vid": "28de", "pid": "1304",
             "unblock_command": rhd.udev_unblock_command(0x28de), "deviceType": "gamepad"},
        ]

def test_simulate_both_report_after_both_rules():
    with simulate_env() as sim_dir:
        for vid in (0x3434, 0x28de):
            with open(os.path.join(sim_dir, rhd.udev_rule_path(vid).rsplit("/", 1)[1]), "w") as f:
                f.write(rhd.UDEV_HEADER + "\n" + rhd.udev_rule_for(vid) + "\n")
        assert json.loads(run_main_capture()) == [
            {"name": "Keychron M5", "serial": "sim-keychron-m5", "percentage": 88, "charging": False, "deviceType": "mouse"},
            {"name": "Steam Controller 2", "serial": "sim-steam-controller-2", "percentage": 85, "charging": True, "deviceType": "gamepad"},
        ]


# ══════════════════════════════════════════════════════════════════════════
# Report-descriptor usage pages: selecting the battery node among a device's
# interfaces when the interface number cannot say which one carries it
# ══════════════════════════════════════════════════════════════════════════
def test_parse_usage_pages_detects_vendor_page():
    assert rhd._parse_usage_pages(bytes([0x06, 0x43, 0xFF, 0x0A, 0x02, 0x02]) + b"\xC0") == {0xFF43}

def test_parse_usage_pages_skips_long_items():
    # 0xFE = long item: next byte is the payload length, which must not be
    # decoded as items or it would fabricate usage pages
    data = bytes([0xFE, 0x03, 0x06, 0x43, 0xFF,
                  0x06, 0x01, 0xFF, 0x0A, 0x02, 0x02])
    assert rhd._parse_usage_pages(data) == {0xFF01}

def test_parse_usage_pages_tolerates_garbage():
    assert rhd._parse_usage_pages(b"") == set()
    assert rhd._parse_usage_pages(b"\xFF\xFF\xFF\xFF") == set()  # truncated items

def test_parse_usage_pages_realistic_mouse_descriptor():
    # 4 collections (generic desktop, buttons+LEDs, consumer, vendor) in one
    # node; the flat set is what the page test needs, so every page comes back
    data = (bytes([0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0xC0])
            + bytes([0x05, 0x09, 0x19, 0x01, 0x29, 0x02, 0x15, 0x00, 0x25, 0x01,
                     0x75, 0x01, 0x95, 0x02, 0x05, 0x08, 0x19, 0x01, 0x29, 0x02,
                     0x09, 0x01, 0x81, 0x02, 0x75, 0x01, 0x95, 0x02, 0x81, 0x01,
                     0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0xC0])
            + bytes([0x06, 0x00, 0xFF, 0x09, 0x02, 0x15, 0x00, 0x25, 0x01,
                     0x75, 0x01, 0x95, 0x01, 0x81, 0x02, 0x75, 0x01, 0x95, 0x01,
                     0x81, 0x01, 0xC0]))
    assert rhd._parse_usage_pages(data) == {0x01, 0x08, 0x09, 0x0C, 0xFF00}

def test_parse_usage_pages_two_byte_usage_keeps_the_current_page():
    # a 2-byte Usage is a usage ID within the current page, NOT a page number
    # in its high byte: 0x0A 0x02 0x02 under page 0xff43 stays on 0xff43
    data = bytes([0x06, 0x43, 0xFF, 0x0A, 0x02, 0x02])
    assert rhd._parse_usage_pages(data) == {0xFF43}, "no fabricated 0x02 page"

def test_match_device_selects_node_by_usage_page_not_iface():
    with vendor_device(0xFF01):
        assert rhd.match_device(_TEST_VID, _TEST_PID, 3, {0xFF01}) is not None
        assert rhd.match_device(_TEST_VID, _TEST_PID, 0, {0xFF01}) is not None, "iface irrelevant"
        # right PID, wrong descriptor: not the battery node
        assert rhd.match_device(_TEST_VID, _TEST_PID, 3, {0x0C}) is None
        # no descriptor read at all
        assert rhd.match_device(_TEST_VID, _TEST_PID, 3, set()) is None

def test_match_device_vendor_sentinel_accepts_any_vendor_page():
    with vendor_device(rhd.VENDOR_USAGE_PAGE):
        for page in (0xFF00, 0xFF01, 0xFF43, 0xFFFF):
            assert rhd.match_device(_TEST_VID, _TEST_PID, 3, {page}) is not None, hex(page)
        for page in (0x0C, 0x01, 0xFF, 0xFEFF):
            assert rhd.match_device(_TEST_VID, _TEST_PID, 3, {page}) is None, hex(page)

def test_match_device_vendor_sentinel_never_matches_an_unregistered_device():
    # 0xff00 is declared by plenty of non-vendor gear (Razer mice, Microsoft
    # keyboards); the sentinel must stay gated behind a vid/pid match
    assert rhd.match_device(0x1532, 0x005C, 0, {0xFF00}) is None
    assert rhd.match_device(0x045E, 0x00DB, 0, {0xFF00}) is None

def test_discovery_reads_descriptor_and_selects_vendor_node():
    install_vendor_scenario(usage_page=0xFF01)
    with vendor_device(rhd.VENDOR_USAGE_PAGE):
        devs = rhd.find_devices()
    assert [d.devpath for d in devs] == ["/dev/hidraw8"], [d.devpath for d in devs]
    assert scenario["descriptor_reads"] == 1, scenario["descriptor_reads"]

def test_discovery_rejects_node_without_a_vendor_page():
    install_vendor_scenario(usage_page=0x0C)  # consumer-control collection only
    with vendor_device(rhd.VENDOR_USAGE_PAGE):
        assert rhd.find_devices() == []

def test_discovery_unreadable_descriptor_matches_nothing():
    # descriptor present in sysfs but unreadable -> skip, never mis-select
    install_vendor_scenario(usage_page=None)
    with vendor_device(rhd.VENDOR_USAGE_PAGE):
        assert rhd.find_devices() == []
    assert scenario["descriptor_reads"] == 1, scenario["descriptor_reads"]

def test_discovery_picks_battery_node_among_multiple_interfaces():
    # one physical device, two hidraw nodes: only the vendor-page one is the
    # battery collection, so the interface number must not decide
    def uevent(node, iface):
        return (f"DRIVER=hid-generic\nHID_ID=0003:{_TEST_VID:08X}:{_TEST_PID:08X}\n"
                f"HID_NAME=Test Vendor Mouse\n"
                f"HID_PHYS=usb-0000:00:14.0-11/input{iface}\nHID_UNIQ=\n")
    scenario["uevents"] = {"hidraw8": uevent("hidraw8", 3), "hidraw9": uevent("hidraw9", 4)}
    scenario["fake_devs"] = {"/dev/hidraw8": 308, "/dev/hidraw9": 309}
    scenario["deny"] = False
    scenario["writes"] = []
    scenario["write_data"] = []
    scenario["reads"] = []
    scenario["read_sizes"] = []
    scenario["open_flags"] = []
    scenario["reply_buf"] = bytearray(16)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 308
    scenario["descriptors"] = {"hidraw8": hid_descriptor(0xFF01),   # vendor: the battery node
                               "hidraw9": hid_descriptor(0x0C)}     # consumer: not a battery
    scenario["descriptor_reads"] = 0

    with vendor_device(rhd.VENDOR_USAGE_PAGE):
        devs = rhd.find_devices()
    # one entry per physical device, and it is the vendor node (iface 3)
    assert [d.devpath for d in devs] == ["/dev/hidraw8"], [d.devpath for d in devs]
    assert scenario["descriptor_reads"] == 2, "one descriptor read per candidate node"

def test_descriptor_read_only_for_usage_page_pids():
    # descriptors are only read for PIDs with a usage_page variant
    install_m5_scenario()                     # iface-only device
    rhd.find_devices()
    assert scenario["descriptor_reads"] == 0, f"M5 must not read descriptors: {scenario['descriptor_reads']}"
    install_vendor_scenario()                 # usage-page device
    with vendor_device(rhd.VENDOR_USAGE_PAGE):
        rhd.find_devices()
    assert scenario["descriptor_reads"] == 1, f"vendor device reads exactly one: {scenario['descriptor_reads']}"


# ══════════════════════════════════════════════════════════════════════════
# SC2: stream read (no request)
# ══════════════════════════════════════════════════════════════════════════
def test_sc2_stream_read():
    install_sc2_scenario()
    set_sc2_report(state=0x02, pct=85)
    sdev = rhd.find_devices()[0]
    assert sdev.desc.name == "Steam Controller 2"
    assert rhd.read_status(sdev) == {"percentage": 85, "charging": True}, "state=0x02 puck -> charging"
    assert scenario["writes"] == [], f"stream: no request written, got {scenario['writes']!r}"


# ══════════════════════════════════════════════════════════════════════════
# --debug diagnostics (stderr only; stdout stays the JSON the widget reads)
# ══════════════════════════════════════════════════════════════════════════
@contextlib.contextmanager
def debug_stderr():
    saved = rhd._DEBUG
    rhd._DEBUG = True
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            yield stderr
    finally:
        rhd._DEBUG = saved

def test_debug_output_explains_an_unanswered_request():
    # which node, which request, what came back, why it was rejected, and that
    # the read then timed out
    install_m5_scenario()
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [bytes([0xB4, 0x00] + [0x00] * 20)]
    with debug_stderr() as stderr:
        devs = rhd.find_devices()
        assert rhd._device_entry(devs[0]) is None
    log = stderr.getvalue()
    assert all(line.startswith("[batterywatch] ") for line in log.splitlines() if line), log
    assert "/dev/hidraw6" in log and "Keychron M5" in log, "device identity + node"
    assert "3434:d028" in log and "iface 4" in log, "identity + selected interface"
    assert "write b3 06 00 00 00" in log, "request bytes"
    assert "received b4 00 00 00 00" in log, "received packet bytes"
    assert "device address 0x00 does not echo the requested 0x06" in log, "rejection reason"
    assert "no accepted reply (report 0xb4) within 1s" in log, "timeout"

def test_debug_output_records_dropped_entry():
    install_m5_scenario()
    scenario["reply_buf"] = bytearray(0)
    with debug_stderr() as stderr:
        assert rhd._device_entry(rhd.find_devices()[0]) is None
    assert "entry dropped" in stderr.getvalue()

def test_debug_output_records_open_and_write_failures():
    install_m5_scenario(with_blocked=True)
    with debug_stderr() as stderr:
        assert rhd.read_status(rhd.find_devices()[0]) is None
    assert "open(/dev/hidraw6, O_RDWR) failed: [Errno 13] Permission denied" in stderr.getvalue()


# ══════════════════════════════════════════════════════════════════════════
# Helper as a subprocess (real run, no device)
# ══════════════════════════════════════════════════════════════════════════
def test_helper_compiles():
    assert py_compile.compile(HELPER, doraise=True) is not None

@contextlib.contextmanager
def real_os():
    # A subprocess needs the REAL os.read/write/close/listdir and select.poll -
    # the scenario monkey-patches live on the shared os/select modules and would
    # corrupt pipe I/O, so restore them around the run, then re-patch.
    os.open, os.write, os.read, os.close = real_osopen, real_oswrite, real_osread, real_osclose
    os.listdir = real_listdir
    select.poll = real_poll
    try:
        yield
    finally:
        patch_module()

def test_helper_real_run_emits_valid_json():
    with real_os():
        r = subprocess.run([sys.executable, HELPER], capture_output=True, text=True,
                           cwd=os.path.dirname(HELPER), timeout=30)
    assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr!r}"
    parsed = json.loads(r.stdout.strip())
    assert isinstance(parsed, list), f"stdout={r.stdout.strip()!r}"

def test_debug_flag_keeps_stdout_valid_json():
    with real_os():
        r = subprocess.run([sys.executable, HELPER, "--debug", "--simulate"], capture_output=True,
                           text=True, cwd=os.path.dirname(HELPER), timeout=30)
    assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr!r}"
    assert isinstance(json.loads(r.stdout.strip()), list), f"stdout={r.stdout.strip()!r}"


# ══════════════════════════════════════════════════════════════════════════
# Zero-dependency runner: collects the test_*() functions above and runs them
# in definition order. pytest discovers the same functions if it's installed.
# ══════════════════════════════════════════════════════════════════════════
def main():
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    failed = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            failed.append(name)
            print(f"FAIL  {name}")
            if e.args:
                print(f"      {e.args[0]}")
        except Exception as e:
            failed.append(name)
            print(f"ERROR {name}: {type(e).__name__}: {e}")
        else:
            print(f"PASS  {name}")
    passed = len(tests) - len(failed)
    print(f"\n{passed}/{len(tests)} checks passed")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
