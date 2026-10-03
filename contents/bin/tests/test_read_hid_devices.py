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
  SC2 (stream):   battery decode from stream report, charging state, no write.
  M3 (Keychron):  2.4 GHz Link dongle - bridge-node discovery by usage page,
                  the feature-report handshake (exact report size, busy
                  retry, stalled read), battery and charging decode.
  Logitech:       HID++ request/validation/voltage decode per headset model.

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
import errno
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
            "open_flags": [], "descriptors": {}, "descriptor_reads": 0,
            "ioctls": [], "feature_sets": [], "feature_answer": None}

def m5_uevent(node, pid="0000D028", name="Keychron Keychron Ultra-Link 8K", iface=4):
    return (f"DRIVER=hid-generic\nHID_ID=0003:00003434:{pid}\n"
            f"HID_NAME={name}\nHID_PHYS=usb-0000:00:14.0-11/input{iface}\nHID_UNIQ=\n")

def keychron_link_uevent(node, pid="0000D031", iface=2):
    return (f"DRIVER=hid-generic\nHID_ID=0003:00003434:{pid}\n"
            f"HID_NAME=Keychron  Keychron Link \n"
            f"HID_PHYS=usb-0000:07:00.3-4/input{iface}\nHID_UNIQ=\n")

def azoth_uevent(node, pid="00001ACE", iface=1):
    return (f"DRIVER=hid-generic\nHID_ID=0003:00000B05:{pid}\n"
            f"HID_NAME=ROG Azoth\nHID_PHYS=usb-0000:00:14.0-12/input{iface}\n"
            "HID_UNIQ=SN1LAZOTG6C2\n")

def fake_open(path, mode="r", *a, **k):
    if path.startswith("/sys/class/hidraw"):
        node = path.split("/")[4]
        if path.endswith("report_descriptor"):
            scenario["descriptor_reads"] += 1
            return io.BytesIO(scenario["descriptors"].get(node, b""))
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

class FakeFcntl:
    # Stand-in for the fcntl module: the Link dongle's feature reports travel
    # through HIDIOCSFEATURE (0x06) / HIDIOCGFEATURE (0x07), whose request number
    # carries the report size in bits 16-29. Rebound as rhd.fcntl, so the real
    # module stays untouched for the subprocess runs.
    def ioctl(self, fd, request, buf, *args):
        number, length = request & 0xFF, (request >> 16) & 0x3FFF
        scenario["ioctls"].append((fd, number, length))
        if number == 0x07:
            answer = scenario["feature_answer"]
            if answer is None:
                raise OSError(errno.EPIPE, os.strerror(errno.EPIPE))
            # like the kernel, the driver fills the report and the helper has to
            # have put the report ID in place itself
            buf[1:len(answer)] = answer[1:]
        else:
            scenario["feature_sets"].append(bytes(buf))
        return 0

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
    scenario["reply_buf"] = bytearray(64)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 306
    scenario["descriptors"] = {}
    scenario["descriptor_reads"] = 0

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
    scenario["reply_buf"] = bytearray(16)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 207
    scenario["descriptors"] = {}
    scenario["descriptor_reads"] = 0

def hid_descriptor(usage_page=0xFF43):
    # minimal HID report descriptor declaring one usage page + a 2-byte usage
    page_item = bytes([0x05, usage_page]) if usage_page <= 0xFF else bytes([0x06, usage_page & 0xFF, (usage_page >> 8) & 0xFF])
    return page_item + bytes([0x0A, 0x02, 0x02]) + b"\xC0"

def install_g733_scenario(iface=3, usage_page=0xFF43, with_blocked=False):
    # Logitech HID++ headset: battery node on usage page 0xff43 (iface is now
    # irrelevant to matching - only the report descriptor page decides), request
    # 11 ff 08 0a, long 0x11 reply (the G733 descriptor in issue #2 declares
    # 85 11 and no 0x10; no reply from real hardware has been captured yet)
    scenario["uevents"] = {
        "hidraw8": ("DRIVER=hid-generic\nHID_ID=0003:0000046D:00000AB5\n"
                    "HID_NAME=Logitech G733 LIGHTSPEED\n"
                    f"HID_PHYS=usb-0000:00:14.0-11/input{iface}\nHID_UNIQ=\n"),
    }
    scenario["fake_devs"] = {"/dev/hidraw8": 208}
    scenario["deny"] = with_blocked
    scenario["writes"] = []
    scenario["write_data"] = []
    scenario["reads"] = []
    scenario["read_sizes"] = []
    scenario["open_flags"] = []
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 208
    scenario["descriptors"] = {"hidraw8": hid_descriptor(usage_page)} if usage_page is not None else {}
    scenario["descriptor_reads"] = 0

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
    scenario["reply_buf"] = bytearray(65)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 309 if pid == "00001ACE" else 308
    scenario["descriptors"] = {}
    scenario["descriptor_reads"] = 0

def install_keychron_link_scenario(with_blocked=False):
    # The Link dongle exposes several HID nodes and only its bridge collection
    # (usage page 0x8C) talks - and it talks in feature reports, not writes
    scenario["uevents"] = {
        "hidraw0": keychron_link_uevent("hidraw0", iface=0),
        "hidraw1": keychron_link_uevent("hidraw1", iface=1),
        "hidraw2": keychron_link_uevent("hidraw2", iface=2),
    }
    scenario["descriptors"] = {
        "hidraw0": hid_descriptor(0x0001),
        "hidraw1": hid_descriptor(0x0001),
        "hidraw2": hid_descriptor(0x8C),
    }
    scenario["fake_devs"] = {f"/dev/hidraw{n}": 300 + n for n in range(3)}
    scenario["deny"] = with_blocked
    scenario["writes"] = []
    scenario["write_data"] = []
    scenario["reads"] = []
    scenario["read_sizes"] = []
    scenario["open_flags"] = []
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 302
    scenario["descriptor_reads"] = 0
    scenario["ioctls"] = []
    scenario["feature_sets"] = []
    scenario["feature_answer"] = None

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

def link_state_packet(header=0x01, connected=0x01, power=0x00, battery=90, length=20):
    # The mouse state packet, payload only: header naming the protocol, the
    # connection state at byte 3, then the power/battery pair (8K Nordic mice
    # carry it further up the packet)
    payload = bytearray(length)
    payload[0], payload[3] = header, connected
    power_at, battery_at = (10, 11) if header == 0x41 else (5, 6)
    payload[power_at], payload[battery_at] = power, battery
    return bytes(payload)

def link_feature_answer(**kwargs):
    return bytes([0x51]) + link_state_packet(**kwargs)

def link_ack(ready=True, marker=0xE4):
    # Input report 0x54: ACK marker, then ready (answer can be read) or busy
    return bytes([0x54, marker, 0x01 if ready else 0x00]) + b"\x00" * 17

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
    rhd.fcntl = FakeFcntl()

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
# Keychron M3 (2.4 GHz Link dongle): feature-report handshake
# ══════════════════════════════════════════════════════════════════════════
@contextlib.contextmanager
def fast_link_retry():
    # The dongle's "busy" back-off is half a second of real time; no test needs
    # to wait it out
    saved = rhd.LINK_RETRY_SEC
    rhd.LINK_RETRY_SEC = 0
    try:
        yield
    finally:
        rhd.LINK_RETRY_SEC = saved

def test_link_reference_profile():
    dev = next(dev for dev in rhd.KNOWN_DEVICES if dev.name == "Keychron M3")
    assert dev.device_type == rhd.DeviceType.MOUSE
    assert dev.variants == (rhd.DeviceVariant(0xD031, None, usage_page=0x8C),)
    # a plain RequestSchema that happens to travel as a feature report
    assert dev.source.request == bytes.fromhex("01008101") + b"\x00" * 16, "state probe, zero-padded"
    assert dev.source.feature_report == 0x51
    assert dev.source.handshake is rhd._keychron_link_handshake

def test_link_discovery_targets_the_bridge_collection():
    install_keychron_link_scenario()
    devs = rhd.find_devices()
    assert [d.devpath for d in devs] == ["/dev/hidraw2"], f"found: {[d.devpath for d in devs]!r}"
    assert devs[0].pid == 0xD031
    assert devs[0].serial == "usb-0000:07:00.3-4"

def test_link_discovery_needs_the_bridge_usage_page():
    install_keychron_link_scenario()
    scenario["descriptors"]["hidraw2"] = hid_descriptor(0x0001)
    assert rhd.find_devices() == []

def test_link_command_is_a_feature_report_at_the_reports_own_size():
    install_keychron_link_scenario()
    scenario["reply_queue"] = [link_ack()]
    scenario["feature_answer"] = link_feature_answer(battery=90)
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 90, "charging": False}
    assert scenario["feature_sets"] == [bytes.fromhex("51") + bytes.fromhex("01008101") + b"\x00" * 16], \
        "the state probe, behind the feature report's own ID"
    assert scenario["ioctls"] == [(302, 0x06, 21), (302, 0x07, 21)], "SET then GET, both 21 bytes"
    assert scenario["writes"] == [], "feature reports never go through write()"

def test_link_decodes_charging_and_the_8k_nordic_layout():
    install_keychron_link_scenario()
    scenario["reply_queue"] = [link_ack()]
    scenario["feature_answer"] = link_feature_answer(header=0x41, power=0x01, battery=57)
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 57, "charging": True}

def test_link_nordic_discharging_state_decodes_as_not_charging():
    install_keychron_link_scenario()
    scenario["reply_queue"] = [link_ack()]
    scenario["feature_answer"] = link_feature_answer(header=0x41, power=0x03, battery=57)
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 57, "charging": False}

def test_link_reads_a_state_packet_mirrored_into_the_acknowledgement():
    # the acknowledgement report is the same size as the state packet, so the
    # dongle may answer in either - accept both
    install_keychron_link_scenario()
    scenario["reply_queue"] = [bytes([0x54]) + link_state_packet(battery=64)]
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 64, "charging": False}
    assert scenario["ioctls"] == [(302, 0x06, 21)], "the answer needs no feature read"

def test_feature_report_command_is_answered_without_a_handshake():
    # the handshake is only for devices that acknowledge the command first;
    # any other feature-report device is simply read back
    install_keychron_link_scenario()
    scenario["feature_answer"] = link_feature_answer(battery=77)
    dev = rhd.find_devices()[0]
    dev = dev._replace(source=dev.source._replace(handshake=None))
    assert rhd.read_status(dev) == {"percentage": 77, "charging": False}
    assert scenario["ioctls"] == [(302, 0x06, 21), (302, 0x07, 21)], "SET then GET"

def test_link_sends_the_command_again_when_the_dongle_is_busy():
    install_keychron_link_scenario()
    scenario["reply_queue"] = [link_ack(ready=False), link_ack()]
    scenario["feature_answer"] = link_feature_answer(battery=30)
    with fast_link_retry():
        assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 30, "charging": False}
    assert scenario["ioctls"] == [(302, 0x06, 21), (302, 0x06, 21), (302, 0x07, 21)]

def test_link_ignores_other_reports_on_the_bridge_node():
    # neither the 8K motion flood, nor an unknown header, nor a frame too short
    # to hold the battery counts as the answer we asked for
    install_keychron_link_scenario()
    scenario["reply_queue"] = [bytes.fromhex("b1 00 10 00 01 02 03 04"),
                               bytes.fromhex("54 02 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"),
                               bytes.fromhex("54 01 00 00")]
    assert rhd.read_status(rhd.find_devices()[0]) is None

def test_link_silence_reports_nothing():
    install_keychron_link_scenario()
    assert rhd.read_status(rhd.find_devices()[0]) is None

def test_link_stalled_or_unrelated_feature_read_reports_nothing():
    # A feature read at the wrong size stalls (EPIPE) - what the issue #48 probe
    # hit with every length but the report's own
    install_keychron_link_scenario()
    scenario["reply_queue"] = [link_ack()]
    assert rhd.read_status(rhd.find_devices()[0]) is None
    # and a feature report that is not a state packet is never decoded as one
    install_keychron_link_scenario()
    scenario["reply_queue"] = [link_ack()]
    scenario["feature_answer"] = link_feature_answer(connected=0x02)
    assert rhd.read_status(rhd.find_devices()[0]) is None

def test_link_blocked_entry_needs_the_shared_keychron_rule():
    install_keychron_link_scenario(with_blocked=True)
    dev = rhd.find_devices()[0]
    assert rhd.is_blocked(dev) is True
    entry = rhd._device_entry(dev)
    assert entry["blocked"] is True
    assert entry["pid"] == "d031"
    assert entry["unblock_command"] == rhd.udev_unblock_command(0x3434)

def test_link_debug_output_shows_the_handshake():
    install_keychron_link_scenario()
    scenario["reply_queue"] = [link_ack(ready=False), link_ack()]
    scenario["feature_answer"] = link_feature_answer(battery=12)
    with fast_link_retry(), debug_stderr() as stderr:
        assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 12, "charging": False}
    log = stderr.getvalue()
    assert "SETFEATURE 0x51 01 00 81 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00" in log, log
    assert "received 54 e4 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00" in log, log
    assert "dongle was busy, sending the request again" in log, "the retry is logged"
    assert "feature report holds 51 01 00 00 01 00 00 0c 00 00 00 00 00 00 00 00 00 00 00 00" in log, log
    assert "reading {'percentage': 12, 'charging': False}" in log, log


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
    stream_variant = rhd.FoundDevice(m5.devpath, m5.serial, request_device, m5.pid, stream_device.source)
    assert rhd.is_blocked(stream_variant) is False
    assert scenario["open_flags"] == [os.O_RDONLY | os.O_NONBLOCK]


# ══════════════════════════════════════════════════════════════════════════
# Per-device udev rule command (one rule file per device/vid)
# ══════════════════════════════════════════════════════════════════════════
def test_udev_rule_path_is_vid_wide():
    assert rhd.udev_rule_path(0x3434) == "/etc/udev/rules.d/70-batterywatch-hid-3434.rules"

def test_keychron_rule_covers_every_variant():
    rule = rhd.udev_rule_for(0x3434)
    assert rule.count('ATTRS{idProduct}') == 3, "one line per variant"
    assert 'ATTRS{idProduct}=="d028"' in rule
    assert 'ATTRS{idProduct}=="d048"' in rule
    assert 'ATTRS{idProduct}=="d031"' in rule

def test_keychron_rule_uses_write_mode():
    # the M5 and the M3 dongle both send commands, so they share one write rule
    assert rhd.udev_rule_for(0x3434).count('MODE="0660"') == 3

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
            {"name": "Logitech G733", "serial": "sim-g733", "blocked": True, "vid": "046d", "pid": "0ab5",
             "unblock_command": rhd.udev_unblock_command(0x046d), "deviceType": "audio-headset"},
        ]

def test_simulate_m5_reports_after_its_rule():
    with simulate_env() as sim_dir:
        with open(os.path.join(sim_dir, "70-batterywatch-hid-3434.rules"), "w") as f:
            f.write(rhd.UDEV_HEADER + "\n" + rhd.udev_rule_for(0x3434) + "\n")
        assert json.loads(run_main_capture()) == [
            {"name": "Keychron M5", "serial": "sim-keychron-m5", "percentage": 88, "charging": False, "deviceType": "mouse"},
            {"name": "Steam Controller 2", "serial": "sim-steam-controller-2", "blocked": True, "vid": "28de", "pid": "1304",
             "unblock_command": rhd.udev_unblock_command(0x28de), "deviceType": "gamepad"},
            {"name": "Logitech G733", "serial": "sim-g733", "blocked": True, "vid": "046d", "pid": "0ab5",
             "unblock_command": rhd.udev_unblock_command(0x046d), "deviceType": "audio-headset"},
        ]

def test_simulate_both_report_after_both_rules():
    with simulate_env() as sim_dir:
        for vid in (0x3434, 0x28de):
            with open(os.path.join(sim_dir, rhd.udev_rule_path(vid).rsplit("/", 1)[1]), "w") as f:
                f.write(rhd.UDEV_HEADER + "\n" + rhd.udev_rule_for(vid) + "\n")
        assert json.loads(run_main_capture()) == [
            {"name": "Keychron M5", "serial": "sim-keychron-m5", "percentage": 88, "charging": False, "deviceType": "mouse"},
            {"name": "Steam Controller 2", "serial": "sim-steam-controller-2", "percentage": 85, "charging": True, "deviceType": "gamepad"},
            {"name": "Logitech G733", "serial": "sim-g733", "blocked": True, "vid": "046d", "pid": "0ab5",
             "unblock_command": rhd.udev_unblock_command(0x046d), "deviceType": "audio-headset"},
        ]


# ══════════════════════════════════════════════════════════════════════════
# Logitech headset (G733): HID++ request + voltage read
#
# SYNTHETIC PROTOCOL FIXTURES - no Logitech battery reply has ever been
# captured. The issue #2 log holds the G733's report descriptor, which proves
# the battery node declares the long report 0x11 (85 11, 19 bytes), but no
# captured reply bytes. The frames below are therefore built from the
# documented HID++ 2.0 frame layout (Logitech/cpg-docs hidpp20 tables, Solaar
# hidpp20) rather than from a recording:
#   [0] report id (0x11 long, 20 bytes; HID++ 2.0 also defines a 7-byte short 0x10)
#   [1] device index (echo of 0xff)   [2] feature index   [3] function/software id
#   [4..5] voltage (big endian)   [6] charge state (0x01 discharging, 0x03 charging)
#   error reply: feature index 0xff + echoed feature/function + code at byte 5
# ══════════════════════════════════════════════════════════════════════════
def g733_frame(report_id=0x11, device=0xFF, feature=0x08, func=0x0A,
               voltage_mv=0, state=0x01, error=None, length=None):
    if error is not None:
        frame = bytes([report_id, device, 0xFF, feature, func, error])
    else:
        frame = bytes([report_id, device, feature, func,
                       (voltage_mv >> 8) & 0xFF, voltage_mv & 0xFF, state])
    return bytearray(frame.ljust(length if length is not None
                                 else (20 if report_id == 0x11 else 7), b"\x00"))

def set_g733_reply(*args, **kwargs):
    scenario["reply_buf"] = g733_frame(*args, **kwargs)

def g733_reads(report_id=0x11, **kwargs):
    """Runs one read against a standing single-frame reply."""
    install_g733_scenario()
    set_g733_reply(report_id=report_id, **kwargs)
    return rhd.read_status(rhd.find_devices()[0])

def test_voltage_percentage_curve():
    assert rhd._voltage_percentage(4100, rhd.G633_CURVE) == 100
    assert rhd._voltage_percentage(4050, rhd.G633_CURVE) == 93   # 80 + 20 * 100/150 between 3950-4100
    assert rhd._voltage_percentage(3150, rhd.G633_CURVE) == 0
    assert rhd._voltage_percentage(3000, rhd.G633_CURVE) == 0    # below curve floor -> clamp to 0

def test_logitech_long_reply_produces_battery_reading():
    # the G733's descriptor declares only the long report 0x11 (issue #2)
    assert g733_reads(report_id=0x11, voltage_mv=4050, state=0x01) == {"percentage": 93, "charging": False}

def test_logitech_short_reply_is_not_accepted():
    # the G733's descriptor (issue #2) declares report 0x11 and no 0x10, and
    # hid-generic cannot deliver an undeclared report, so a 0x10 packet must
    # never be read as a battery reply
    assert g733_reads(report_id=0x10, voltage_mv=4050, state=0x01) is None

def test_logitech_long_reply_charging():
    assert g733_reads(report_id=0x11, voltage_mv=4100, state=0x03) == {"percentage": 100, "charging": True}

def test_logitech_request_is_unchanged():
    install_g733_scenario()
    gdev = rhd.find_devices()[0]
    assert gdev.desc.source.request == bytes([0x11, 0xFF, 0x08, 0x0A]) + b"\x00" * 16, "20-byte long request"
    set_g733_reply(report_id=0x11, voltage_mv=4050, state=0x01)
    rhd.read_status(gdev)
    assert scenario["write_data"] == [bytes([0x11, 0xFF, 0x08, 0x0A]) + b"\x00" * 16], \
        f"request sent to the device: {scenario['write_data']!r}"

def test_logitech_profile_waits_for_the_long_report_only():
    install_g733_scenario()
    schema = rhd.find_devices()[0].source
    assert rhd.needed_reports(schema) == {0x11: 7}, "7 bytes through the charge state"
    assert schema.charge == rhd.DataPos(0x11, 4) and schema.charge_range is None
    assert not hasattr(rhd, "accepted_ids") and not hasattr(rhd, "reply_complete"), \
        "no alternative-reply machinery left: one report ID per schema"
    assert not hasattr(schema, "valid"), "rejection_reason() is the single validity check"

def test_logitech_ignores_unrelated_packets_until_the_matching_reply():
    install_g733_scenario()
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [
        bytearray(8),                          # a HID++ event on the same node
        g733_frame(report_id=0x11, feature=0x04, voltage_mv=4050),   # other feature
        g733_frame(report_id=0x11, func=0x15, voltage_mv=4050),      # other function
        g733_frame(report_id=0x11, device=0x00, voltage_mv=4050),    # no device addressed
        g733_frame(report_id=0x11, voltage_mv=0xFFFF),                # implausible voltage
        g733_frame(report_id=0x11, voltage_mv=4050, state=0x01),      # the real reply
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 93, "charging": False}
    assert len(scenario["reads"]) == 6, f"every queued packet was read: {len(scenario['reads'])}"

def test_logitech_other_report_ids_are_not_battery_frames():
    install_g733_scenario()
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [g733_frame(report_id=0x01, voltage_mv=4050)]
    assert rhd.read_status(rhd.find_devices()[0]) is None

def test_logitech_rejects_wrong_address_feature_and_function():
    install_g733_scenario()
    check = rhd.find_devices()[0].source.rejection_reason
    assert check(g733_frame(report_id=0x11, device=0x00, voltage_mv=4050)), "0x00 addresses no device"
    assert check(g733_frame(report_id=0x11, feature=0x04, voltage_mv=4050)), "other feature"
    assert check(g733_frame(report_id=0x11, func=0x15, voltage_mv=4050)), "other function"
    assert check(g733_frame(report_id=0x11, voltage_mv=4050)) is None, "the battery reply itself"

def test_logitech_rejects_replies_meant_for_another_address_or_application():
    # byte 1 is the device index we addressed (0xff) and byte 3 carries the
    # software ID, which exists to separate replies meant for other applications
    # (Logitech/cpg-docs hidpp20). Accepting a near miss would report whichever
    # stale frame arrived first, so both halves have to match exactly.
    install_g733_scenario()
    check = rhd.find_devices()[0].source.rejection_reason
    for device in (0x00, 0x01, 0x03, 0x0F):
        reason = check(g733_frame(report_id=0x11, device=device, voltage_mv=3600))
        assert reason and "device index" in reason, f"address {device:#04x}: {reason}"
    for func in (0x00, 0x0B, 0x0D):
        reason = check(g733_frame(report_id=0x11, func=func, voltage_mv=3600))
        assert reason and "function/software id" in reason, f"function byte {func:#04x}: {reason}"
    assert check(g733_frame(report_id=0x11, voltage_mv=4050)) is None, "the matching reply itself"

def test_logitech_unrelated_reply_before_the_real_one_is_skipped():
    # the matching bug: a frame that is not ours arrives first and used to be
    # reported instead of the battery reply that followed it
    install_g733_scenario()
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [
        g733_frame(report_id=0x11, device=0x03, func=0x00, voltage_mv=3600),
        g733_frame(report_id=0x11, voltage_mv=4050),
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 93, "charging": False}
    assert len(scenario["reads"]) == 2, "the unrelated frame did not end the read"

def test_logitech_truncated_packets_never_crash_or_decode():
    install_g733_scenario()
    check = rhd.find_devices()[0].source.rejection_reason
    reply = g733_frame(report_id=0x11, voltage_mv=4050)
    for length in range(0, 7):
        reason = check(reply[:length])
        assert reason, f"{length}-byte packet must be rejected with a reason"

    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [reply[:n] for n in (1, 2, 3, 5, 6)]
    assert rhd.read_status(rhd.find_devices()[0]) is None, "truncated packets produce no reading"

def test_logitech_validator_checks_the_report_id_itself():
    # the read loop filters report IDs too, but the validator must reject a
    # short 0x10 frame on its own too - issue #47's report id is 0x11
    install_g733_scenario()
    check = rhd.find_devices()[0].source.rejection_reason
    reason = check(g733_frame(report_id=0x10, voltage_mv=4050))
    assert reason and "0x10" in reason and "0x11" in reason, reason
    assert check(g733_frame(report_id=0x11, voltage_mv=4050)) is None

def test_logitech_gpro_series_keeps_issue_47_profile_without_relaxed_matching():
    # issue #47: a PRO X Wireless (0x0aba) answers feature 0x06 with the exact
    # bytes it was sent - 06 00 for a 06 00 request - which a strict check
    # accepts. It stays in the shared G PRO profile; if a model ever needs a
    # different software ID it gets its own profile, not a relaxed check.
    install_g733_scenario()
    gpro = next(d for d in rhd.KNOWN_DEVICES if d.name == "Logitech G PRO Series")
    check, parse = gpro.source.rejection_reason, gpro.parse
    assert 0x0ABA in [v.pid for v in gpro.variants], "the PRO X Wireless keeps its profile"
    assert gpro.source.request[:4] == bytes([0x11, 0xFF, 0x06, 0x0D])
    reply = bytes([0x11, 0xFF, 0x06, 0x0D, 0x0F, 0xD2, 0x01]).ljust(20, b"\x00")
    assert check(reply) is None
    assert parse({0x11: bytearray(reply)}) == {"percentage": 84, "charging": False}
    # issue #47's capture used software ID 0; a reply carrying a software ID we
    # did not send is another application's and is not ours to report
    other = bytes([0x11, 0xFF, 0x06, 0x00, 0x0F, 0xD2, 0x01]).ljust(20, b"\x00")
    reason = check(other)
    assert reason and "function/software id" in reason, reason

def test_logitech_error_reply_is_recorded_and_never_a_voltage():
    # the error frame's bytes 4-5 are the echoed feature/function: 0x080a looks
    # like a 2058 mV battery if an error frame were decoded as a reading
    assert g733_reads(report_id=0x11, error=0x08) is None, "error reply produces no reading"
    install_g733_scenario()
    check = rhd.find_devices()[0].source.rejection_reason
    reason = check(g733_frame(report_id=0x11, error=0x08))
    assert "error reply" in reason and "Busy" in reason, reason
    reason = check(g733_frame(report_id=0x11, error=0x06))
    assert "INVALID_FEATURE_INDEX" in reason, reason

def test_logitech_unmatched_0xff_is_reported_without_guessing_its_meaning():
    # byte 2 = 0xff is a HID++ 2.0 error marker. An error that echoes our own
    # feature/function is ours to report (the kernel's hidpp_match_error rule);
    # one that does not could be answering another application, so it is logged
    # as received and not labelled with a cause we cannot evidence.
    install_g733_scenario()
    check = rhd.find_devices()[0].source.rejection_reason
    reason = check(g733_frame(report_id=0x11, error=0x08))
    assert "error reply answering our request" in reason, reason
    assert "Busy" in reason, "our own error keeps its code"
    other = check(g733_frame(report_id=0x11, feature=0x04, error=0x01))
    assert "not an answer to this request" in other, other
    assert "another feature/function" in other and "code 1" in other, other
    assert "offline" not in other.lower(), f"must not claim the headset is off: {other}"
    assert "headset" not in other.lower(), f"must not claim a device state: {other}"

def test_logitech_error_reply_keeps_waiting_then_reports_nothing():
    install_g733_scenario()
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [
        g733_frame(report_id=0x11, error=0x08),                  # busy
        g733_frame(report_id=0x11, voltage_mv=4050, state=0x01),  # then the real reply
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 93, "charging": False}
    assert len(scenario["reads"]) == 2, "the error frame did not end the read"

def test_logitech_0xff_marker_produces_no_entry():
    # a 0xff feature byte - whatever it means - is never a voltage, and a read
    # that only ever sees one reports nothing
    install_g733_scenario()
    set_g733_reply(report_id=0x11, feature=0x04, error=0x01)   # error for another feature
    assert rhd._device_entry(rhd.find_devices()[0]) is None
    set_g733_reply(report_id=0x11, error=0x01)                 # error for our request
    assert rhd._device_entry(rhd.find_devices()[0]) is None

def test_logitech_voltage_parse_low_voltage_keeps_reading():
    # a below-curve voltage is not the battery frame: keep waiting, then time out
    install_g733_scenario()
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [g733_frame(report_id=0x11, voltage_mv=3100, state=0x01)]
    assert rhd.read_status(rhd.find_devices()[0]) is None

def test_logitech_bad_frame_then_good_frame_keeps_reading():
    # a plausible-looking but wrong frame (implausible voltage) must not be
    # reported; the helper keeps waiting and returns the real battery reply
    install_g733_scenario()
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [
        g733_frame(report_id=0x11, voltage_mv=0xFFFF, state=0x01),   # garbage frame
        g733_frame(report_id=0x11, voltage_mv=4050, state=0x01),     # real reply
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 93, "charging": False}

def test_logitech_g733_match_and_udev_rule():
    install_g733_scenario()
    sdev = rhd.find_devices()[0]
    assert sdev.desc.name == "Logitech G733/G933/G935"
    assert sdev.pid == 0x0AB5
    rule = rhd.udev_rule_for(sdev.desc.vid)
    assert 'MODE="0660"' in rule, "headset needs write access to answer the request"
    assert "SYMLINK" not in rule

def test_logitech_headset_families():
    headsets = {d.name: d for d in rhd.KNOWN_DEVICES if d.device_type == rhd.DeviceType.HEADSET}
    assert set(headsets) == {"Logitech G733/G933/G935", "Logitech G533", "Logitech G535", "Logitech G PRO Series"}
    for d in headsets.values():
        assert all(v.iface == 3 or v.usage_page == 0xFF43 for v in d.variants), \
            f"{d.name}: battery node pinned by interface 3 or vendor usage page"
        assert d.source.request == bytes([0x11, 0xFF, d.source.request[2], d.source.request[3]]) + b"\x00" * 16, f"{d.name}: 20-byte long request"
        # HID++ 2.0 throughout: long request in, long reply out
        assert rhd.needed_reports(d.source) == {0x11: 7}, f"{d.name}: long reply 0x11 only"
        assert d.source.validate_reply is not None, f"{d.name}: reply is validated against the request"
        assert d.parse is not None
    assert [v.pid for v in headsets["Logitech G733/G933/G935"].variants] == [0x0A5B, 0x0A87, 0x0AB5, 0x0AFE, 0x0B1F]
    # G PRO family drops the X2 (0x0AFB/0x0AFC): Solaar lists the X2 as 0x0AF7
    # on the separate Centurion transport, a different protocol family
    assert [v.pid for v in headsets["Logitech G PRO Series"].variants] == [0x0AA7, 0x0AAA, 0x0ABA]
    assert all(v.usage_page == 0xFF43 for v in headsets["Logitech G PRO Series"].variants)
    assert headsets["Logitech G533"].source.request[:4] == bytes([0x11, 0xFF, 0x07, 0x01])
    assert headsets["Logitech G535"].source.request[:4] == bytes([0x11, 0xFF, 0x05, 0x0D])
    assert headsets["Logitech G535"].variants[0].iface == 3, "G535: consumer page is generic, pins interface 3"
    assert headsets["Logitech G PRO Series"].source.request[:4] == bytes([0x11, 0xFF, 0x06, 0x0D])


# ══════════════════════════════════════════════════════════════════════════
# Logitech headset: battery-node discovery via report-descriptor usage page
# ══════════════════════════════════════════════════════════════════════════
def test_parse_usage_pages_detects_vendor_page():
    pages = rhd._parse_usage_pages(bytes([0x06, 0x43, 0xFF, 0x0A, 0x02, 0x02]) + b"\xC0")
    assert 0xFF43 in pages, f"vendor page not detected: {pages!r}"

def test_parse_usage_pages_skips_long_items():
    # a long item (0xFE) before the usage-page item must be skipped cleanly
    data = bytes([0xFE, 0x03, 0xAA, 0xBB, 0xCC, 0x06, 0x43, 0xFF])
    assert 0xFF43 in rhd._parse_usage_pages(data)

def test_parse_usage_pages_tolerates_garbage():
    assert rhd._parse_usage_pages(b"") == set()
    assert rhd._parse_usage_pages(b"\xFF\xFF\xFF\xFF") == set()  # truncated items

def test_discovery_matches_battery_node_by_usage_page_not_iface():
    # the battery node is found by its 0xff43 vendor page even when the kernel
    # numbers the interface 4 (not the Solaar/headsetcontrol "interface 3")
    install_g733_scenario(iface=4)
    devs = rhd.find_devices()
    assert [d.devpath for d in devs] == ["/dev/hidraw8"], f"found: {[d.devpath for d in devs]!r}"

def test_discovery_rejects_node_without_vendor_page():
    install_g733_scenario(usage_page=0x000C)  # consumer page only: not the battery node
    assert rhd.find_devices() == []

def test_discovery_picks_battery_node_among_multiple_interfaces():
    # the dongle exposes several HID nodes: only the one declaring 0xff43 matches
    install_g733_scenario(iface=3)
    scenario["uevents"]["hidraw9"] = (
        "DRIVER=hid-generic\nHID_ID=0003:0000046D:00000AB5\n"
        "HID_NAME=Logitech G733 LIGHTSPEED\n"
        "HID_PHYS=usb-0000:00:14.0-11/input2\nHID_UNIQ=\n")
    scenario["descriptors"]["hidraw9"] = bytes([0x05, 0x0C]) + b"\xC0"  # consumer page, no 0xff43
    scenario["fake_devs"]["/dev/hidraw9"] = 209
    set_g733_reply(report_id=0x11, voltage_mv=4050, state=0x01)  # battery reply on the battery node
    devs = rhd.find_devices()
    assert [d.devpath for d in devs] == ["/dev/hidraw8"], f"found: {[d.devpath for d in devs]!r}"
    assert rhd.read_status(devs[0]) == {"percentage": 93, "charging": False}

def test_discovery_unreadable_descriptor_matches_nothing():
    # a node whose descriptor can't be read is skipped, never mis-selected
    install_g733_scenario(usage_page=None)
    assert rhd.find_devices() == []

def test_descriptor_read_only_for_usage_page_pids():
    # the report descriptor is only read for PIDs with a usage_page variant
    install_m5_scenario()                     # iface-only device
    rhd.find_devices()
    assert scenario["descriptor_reads"] == 0, f"M5 must not read descriptors: {scenario['descriptor_reads']}"
    install_g733_scenario()                   # usage-page device
    rhd.find_devices()
    assert scenario["descriptor_reads"] == 1, f"G733 reads exactly one: {scenario['descriptor_reads']}"


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
    # the finding that issue #2 needed: which node, which request, what came
    # back, why it was rejected, and that the read then timed out
    install_g733_scenario()
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [g733_frame(report_id=0x11, feature=0x04, voltage_mv=4050)]
    with debug_stderr() as stderr:
        devs = rhd.find_devices()
        assert rhd._device_entry(devs[0]) is None
    log = stderr.getvalue()
    assert all(line.startswith("[batterywatch] ") for line in log.splitlines() if line), log
    assert "/dev/hidraw8" in log and "Logitech G733/G933/G935" in log, "device identity + node"
    assert "046d:0ab5" in log and "iface 3" in log, "identity + selected interface"
    assert "write 11 ff 08 0a 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00" in log, "request bytes"
    assert "received 11 ff 04 0a 0f d2 01" in log, "received packet bytes"
    assert "feature index 0x04 is not 0x08" in log, "rejection reason"
    assert "no accepted reply (report 0x11) within 1s" in log, "timeout"

def test_debug_output_records_error_reply_details():
    install_g733_scenario()
    scenario["reply_queue"] = [g733_frame(report_id=0x11, error=0x08)]
    with debug_stderr() as stderr:
        assert rhd._device_entry(rhd.find_devices()[0]) is None
    log = stderr.getvalue()
    assert "HID++ 2.0 error reply answering our request: code 8 (Busy)" in log, log
    assert "entry dropped" in log, log

def test_debug_output_records_open_and_write_failures():
    install_g733_scenario(with_blocked=True)
    with debug_stderr() as stderr:
        assert rhd.read_status(rhd.find_devices()[0]) is None
    assert "open(/dev/hidraw8, O_RDWR) failed: [Errno 13] Permission denied" in stderr.getvalue()


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
