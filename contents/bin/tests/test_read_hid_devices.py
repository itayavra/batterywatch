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
  K57 RGB Wireless (Corsair): Bragi GET-only link, level and status requests
                  through the dongle's command interface, reply validation,
                  no keyboard request while the keyboard is not linked.
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
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import py_compile
import re
import select
import subprocess
import sys
import tempfile
import threading
import time
import types
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, ".."))
HELPER = os.path.join(BIN, "read_hid_devices")

# Capture originals to verify importing this suite leaves stdlib modules intact.
real_listdir = os.listdir
real_osopen = os.open
real_oswrite = os.write
real_osread = os.read
real_osclose = os.close
real_poll = select.poll
real_ioctl = fcntl.ioctl
real_sleep = time.sleep


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
unpatched_feature_exchange = rhd._feature_exchange

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

def hid_descriptor_pages(*pages):
    # Descriptor declaring several usage pages, as real multi-collection
    # interfaces do (one Global Usage Page item each).
    out = b""
    for page in pages:
        out += bytes([0x05, page]) if page <= 0xFF else bytes([0x06, page & 0xFF, page >> 8])
    return out + b"\xC0"

def install_glorious_scenario(pid="00002022", usage_page=0xFF01, with_blocked=False):
    # Glorious Model O Wireless: battery on the vendor collection, selected by
    # report-descriptor usage page; answered over feature reports, not the
    # interrupt endpoint.
    scenario["uevents"] = {
        "hidraw1": ("DRIVER=hid-generic\nHID_ID=0003:0000258A:%s\n"
                    "HID_NAME=Glorious Model O Wireless\n"
                    "HID_PHYS=usb-0000:00:14.0-3/input0\nHID_UNIQ=\n" % pid),
        "hidraw2": ("DRIVER=hid-generic\nHID_ID=0003:0000258A:%s\n"
                    "HID_NAME=Glorious Model O Wireless\n"
                    "HID_PHYS=usb-0000:00:14.0-3/input1\nHID_UNIQ=\n" % pid),
    }
    scenario["fake_devs"] = {"/dev/hidraw1": 401, "/dev/hidraw2": 402}
    scenario["deny"] = with_blocked
    scenario["writes"] = []
    scenario["write_data"] = []
    scenario["reads"] = []
    scenario["read_sizes"] = []
    scenario["open_flags"] = []
    scenario["reply_buf"] = bytearray(65)
    scenario["reply_queue"] = []
    scenario["reply_fd"] = 402
    # only the vendor node (hidraw2) declares the battery usage page
    scenario["descriptors"] = {"hidraw2": hid_descriptor(usage_page)}
    scenario["descriptor_reads"] = 0
    scenario["ioctls"] = []

def set_glorious_reply(pct=42, state=0xA1, cmd=0x83):
    buf = bytearray(65)
    buf[1] = state
    buf[6] = cmd
    buf[8] = pct
    scenario["reply_buf"] = buf

def fake_ioctl(fd, request, buf):
    scenario["ioctls"].append((fd, request, bytes(buf)))
    # GET_FEATURE (nr 0x07) fills the caller's mutable buffer with the reply
    if (request & 0xFF) == 0x07 and fd == scenario["reply_fd"]:
        reply = scenario["reply_buf"][:len(buf)]
        buf[:len(reply)] = reply
        return len(reply)
    return len(buf)

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

# ── Corsair K57 RGB Wireless dongle (1b1c:1b62, Bragi protocol) ─────────────
# The dongle exposes six HID interfaces. Interface 1 is the Bragi command
# channel. Interface 2 shares its vendor page but is input only.
K57_INTERFACE_NODES = {"hidraw5": 0, "hidraw6": 1, "hidraw7": 2,
                       "hidraw8": 3, "hidraw9": 4, "hidraw10": 5}
K57_COMMAND_FD = 401

def k57_request(address, prop):
    return bytes([0x00, address, 0x02, prop]) + b"\x00" * 61

K57_LINK_REQUEST = k57_request(0x08, 0x36)
K57_LEVEL_REQUEST = k57_request(0x09, 0x0F)
K57_STATUS_REQUEST = k57_request(0x09, 0x10)

# Captured on hardware. Byte 0 is the child index (address - 0x08), not the
# address: 0x00 from the dongle, 0x01 from the keyboard. The link value
# 0x0002 has the keyboard bit set, the level value 0x03e8 is 100.0 percent,
# and status value 3 is fully charged.
K57_LINK_REPLY_CAPTURE = bytes.fromhex("00 02 00 02 00") + b"\x00" * 59
K57_LEVEL_REPLY_CAPTURE = bytes.fromhex("01 02 00 e8 03") + b"\x00" * 59
K57_STATUS_REPLY_CAPTURE = bytes.fromhex("01 02 00 03 00") + b"\x00" * 59
# Captured on hardware: GET 0x0f at the dongle address is not supported
K57_DONGLE_LEVEL_REPLY_CAPTURE = bytes.fromhex("00 02 05 a4 6a 00 20") + b"\x00" * 57

def bragi_reply(value=0, status=0x00, command=0x02, length=64, first_byte=0x01):
    buf = bytearray(max(length, 5))
    buf[0] = first_byte
    buf[1] = command
    buf[2] = status
    buf[3:5] = value.to_bytes(2, "little")
    return bytes(buf[:length])

def k57_uevent(iface):
    return ("DRIVER=hid-generic\nHID_ID=0003:00001B1C:00001B62\n"
            "HID_NAME=Corsair K57 RGB Wireless dongle\n"
            f"HID_PHYS=usb-0000:00:14.0-4/input{iface}\n"
            "HID_UNIQ=3E7EE6855E013742\n")

def install_k57_scenario(with_blocked=False, nodes=K57_INTERFACE_NODES,
                         level=873, battery_status=0x02):
    scenario["uevents"] = {node: k57_uevent(iface) for node, iface in nodes.items()}
    scenario["fake_devs"] = {f"/dev/{node}": 400 + iface for node, iface in nodes.items()}
    scenario["deny"] = with_blocked
    scenario["writes"] = []
    scenario["write_data"] = []
    scenario["reads"] = []
    scenario["read_sizes"] = []
    scenario["open_flags"] = []
    scenario["descriptors"] = {}
    scenario["descriptor_reads"] = 0
    scenario["reply_buf"] = bytearray(0)
    scenario["reply_queue"] = [
        K57_LINK_REPLY_CAPTURE,
        bragi_reply(level),
        bragi_reply(battery_status),
    ]
    scenario["reply_fd"] = K57_COMMAND_FD

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
    rhd.os = types.SimpleNamespace(**{**vars(os), "open": fake_osopen,
        "listdir": lambda *a: list(scenario["uevents"].keys()),
        "write": fake_write, "read": fake_read, "close": lambda fd: None})
    rhd.select = types.SimpleNamespace(**{**vars(select), "poll": FakePoller})
    rhd.fcntl = types.SimpleNamespace(**{**vars(fcntl), "ioctl": fake_ioctl})
    rhd.time = types.SimpleNamespace(**{**vars(time), "sleep": lambda _s: None})
    # Protocol tests exercise the worker's real exchange against fake hardware.
    # Separate tests below exercise the subprocess deadline and output delivery.
    rhd._feature_exchange = lambda path, schema: rhd._read_feature_report(path, schema.request, schema.settle)

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
# Corsair K57 RGB Wireless: Bragi GET requests through the 1b62 dongle
# ══════════════════════════════════════════════════════════════════════════
def k57_device():
    return next(dev for dev in rhd.KNOWN_DEVICES
                if dev.name == "Corsair K57 RGB Wireless")

def test_k57_profile_sends_only_the_three_bragi_get_requests():
    dev = k57_device()
    assert dev.device_type == rhd.DeviceType.KEYBOARD
    assert dev.vid == 0x1B1C
    assert dev.variants == (rhd.DeviceVariant(0x1B62, 1),)
    transactions = dev.source.transactions
    assert [transaction.key for transaction in transactions] == ["link", "level", "status"]
    assert [transaction.request for transaction in transactions] == [
        K57_LINK_REQUEST, K57_LEVEL_REQUEST, K57_STATUS_REQUEST
    ]

def test_k57_captured_link_reply_is_accepted():
    install_k57_scenario(level=873, battery_status=0x02)
    assert scenario["reply_queue"][0] == K57_LINK_REPLY_CAPTURE
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 87, "charging": False}
    assert scenario["write_data"] == [K57_LINK_REQUEST, K57_LEVEL_REQUEST, K57_STATUS_REQUEST]
    assert scenario["writes"] == [K57_COMMAND_FD] * 3, "every request goes to the command interface"
    assert scenario["read_sizes"] == [65, 65, 65]
    assert len(scenario["reads"]) == 3

def test_k57_captured_exchange_decodes_100_percent_fully_charged():
    install_k57_scenario()
    scenario["reply_queue"] = [K57_LINK_REPLY_CAPTURE, K57_LEVEL_REPLY_CAPTURE,
                               K57_STATUS_REPLY_CAPTURE]
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 100, "charging": False}
    assert scenario["write_data"] == [K57_LINK_REQUEST, K57_LEVEL_REQUEST, K57_STATUS_REQUEST]
    assert bragi_reply(0x03) == K57_STATUS_REPLY_CAPTURE, "synthetic replies match the capture"

def test_k57_reply_starting_with_the_address_is_accepted_too():
    install_k57_scenario()
    scenario["reply_queue"] = [bragi_reply(0x0002, first_byte=0x08),
                               bragi_reply(873, first_byte=0x09),
                               bragi_reply(0x02, first_byte=0x09)]
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 87, "charging": False}

def test_k57_dongle_reply_is_not_taken_as_the_keyboard_battery():
    install_k57_scenario()
    scenario["reply_queue"] = [K57_LINK_REPLY_CAPTURE,
                               bragi_reply(873, first_byte=0x00),   # the dongle's child index
                               bragi_reply(873), bragi_reply(0x02)]
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 87, "charging": False}
    assert len(scenario["reads"]) == 4

    install_k57_scenario()
    scenario["reply_queue"] = [K57_LINK_REPLY_CAPTURE, K57_DONGLE_LEVEL_REPLY_CAPTURE]
    assert rhd.read_status(rhd.find_devices()[0]) is None
    assert scenario["write_data"] == [K57_LINK_REQUEST, K57_LEVEL_REQUEST]

def test_k57_charging_status_decodes_charging():
    install_k57_scenario(level=456, battery_status=0x01)
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 46, "charging": True}

def test_k57_fully_charged_status_decodes_not_charging():
    install_k57_scenario(level=1000, battery_status=0x03)
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 100, "charging": False}

def test_k57_unlinked_keyboard_sends_no_keyboard_request():
    install_k57_scenario()
    scenario["reply_queue"] = [bragi_reply(0x0001, first_byte=0x00)]   # only the dongle bit set
    assert rhd.read_status(rhd.find_devices()[0]) is None
    assert scenario["write_data"] == [K57_LINK_REQUEST]

def test_k57_bragi_not_supported_status_publishes_nothing():
    install_k57_scenario()
    scenario["reply_queue"] = [K57_LINK_REPLY_CAPTURE, bragi_reply(873, status=0x05)]
    assert rhd.read_status(rhd.find_devices()[0]) is None
    assert scenario["write_data"] == [K57_LINK_REQUEST, K57_LEVEL_REQUEST]

    install_k57_scenario()
    scenario["reply_queue"] = [bragi_reply(0x0002, status=0x05, first_byte=0x00)]
    assert rhd.read_status(rhd.find_devices()[0]) is None
    assert scenario["write_data"] == [K57_LINK_REQUEST]

def test_k57_reply_with_another_first_byte_is_ignored():
    install_k57_scenario()
    scenario["reply_queue"] = [
        K57_LINK_REPLY_CAPTURE,
        bragi_reply(873, first_byte=0x02),   # neither the child index 0x01 nor 0x09
        bragi_reply(873),
        bragi_reply(0x02),
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 87, "charging": False}
    assert len(scenario["reads"]) == 4

    install_k57_scenario()
    scenario["reply_queue"] = [bragi_reply(0x0002, first_byte=0x01)]
    assert rhd.read_status(rhd.find_devices()[0]) is None
    assert scenario["write_data"] == [K57_LINK_REQUEST]

def test_k57_rejects_wrong_length_and_non_get_replies():
    install_k57_scenario()
    scenario["reply_queue"] = [
        K57_LINK_REPLY_CAPTURE[:63],
        bragi_reply(0x0002, command=0x01, first_byte=0x00),
        K57_LINK_REPLY_CAPTURE,
        bragi_reply(873),
        bragi_reply(0x02),
    ]
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 87, "charging": False}
    assert len(scenario["reads"]) == 5

def test_k57_level_outside_1_to_1000_is_rejected():
    for level in (0, 1001):
        install_k57_scenario()
        scenario["reply_queue"] = [K57_LINK_REPLY_CAPTURE, bragi_reply(level)]
        assert rhd.read_status(rhd.find_devices()[0]) is None, level
        assert scenario["write_data"] == [K57_LINK_REQUEST, K57_LEVEL_REQUEST], level

    install_k57_scenario(level=1, battery_status=0x02)
    assert rhd.read_status(rhd.find_devices()[0]) == {"percentage": 0, "charging": False}

def test_k57_unknown_battery_status_is_rejected():
    for battery_status in (0x00, 0x04):
        install_k57_scenario(battery_status=battery_status)
        assert rhd.read_status(rhd.find_devices()[0]) is None, battery_status

def test_k57_second_step_timeout_sends_no_third_request():
    install_k57_scenario()
    scenario["reply_queue"] = [K57_LINK_REPLY_CAPTURE]
    assert rhd.read_status(rhd.find_devices()[0]) is None
    assert scenario["write_data"] == [K57_LINK_REQUEST, K57_LEVEL_REQUEST]

def test_k57_discovery_picks_interface_1_and_never_hidraw7():
    install_k57_scenario()
    devs = rhd.find_devices()
    assert [dev.devpath for dev in devs] == ["/dev/hidraw6"]
    assert devs[0].pid == 0x1B62
    assert scenario["descriptor_reads"] == 0, "the interface number alone selects the node"

    install_k57_scenario(nodes={node: iface for node, iface in K57_INTERFACE_NODES.items()
                                if node != "hidraw6"})
    assert rhd.find_devices() == [], "hidraw7 shares the vendor page but is input only"

def test_k57_every_request_is_a_bragi_get():
    install_k57_scenario()
    assert rhd.read_status(rhd.find_devices()[0]) is not None
    for transaction in k57_device().source.transactions:
        assert len(transaction.request) == 65
        assert transaction.request[0] == 0x00, "report number of a report-id-less interface"
        assert transaction.request[2] == 0x02, "GET only, never SET"
    assert len(scenario["write_data"]) == 3
    for packet in scenario["write_data"]:
        assert packet[1] in (0x08, 0x09), f"not addressed to the dongle or keyboard: {packet.hex(' ')}"
        assert packet[2] == 0x02, f"non-GET packet written: {packet.hex(' ')}"
        assert packet[3] in (0x36, 0x0F, 0x10), f"unexpected property: {packet.hex(' ')}"
        assert not any(packet[4:]), f"GET carries no payload: {packet.hex(' ')}"

def test_k57_serial_is_the_dongle_usb_serial():
    install_k57_scenario()
    entry = rhd._device_entry(rhd.find_devices()[0])
    assert entry == {"name": "Corsair K57 RGB Wireless", "serial": "3E7EE6855E013742",
                     "percentage": 87, "charging": False, "deviceType": "keyboard"}

def test_k57_blocked_entry_and_udev_rule():
    install_k57_scenario(with_blocked=True)
    dev = rhd.find_devices()[0]
    assert rhd.is_blocked(dev) is True
    entry = rhd._device_entry(dev)
    assert entry["blocked"] is True
    assert entry["vid"] == "1b1c"
    assert entry["pid"] == "1b62"
    rule = rhd.udev_rule_for(0x1B1C)
    assert 'ATTRS{idProduct}=="1b62"' in rule
    assert rule.count('MODE="0660"') == 1


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

def test_udev_rule_matches_each_variant_interface():
    lines = rhd.udev_rule_for(0x0B05).split("\n")
    by_pid = {pid: [line for line in lines if f'ATTRS{{idProduct}}=="{pid}"' in line]
              for pid in ("1a83", "1a85", "1ace")}
    assert all(len(found) == 1 for found in by_pid.values()), by_pid
    assert 'ENV{ID_USB_INTERFACE_NUM}=="01"' in by_pid["1a83"][0]
    assert 'ENV{ID_USB_INTERFACE_NUM}=="01"' in by_pid["1a85"][0]
    assert 'ENV{ID_USB_INTERFACE_NUM}=="02"' in by_pid["1ace"][0]
    assert rhd.udev_rule_for(0x3434).count('ENV{ID_USB_INTERFACE_NUM}=="04"') == 2
    sc2 = rhd.udev_rule_for(0x28DE)
    assert 'ATTRS{idProduct}=="1302", ENV{ID_USB_INTERFACE_NUM}=="00"' in sc2
    assert 'ATTRS{idProduct}=="1304", ENV{ID_USB_INTERFACE_NUM}=="02"' in sc2

def test_udev_rule_imports_usb_id_before_matching_the_interface():
    # systemd before v258 does not import usb_id for hidraw nodes, so the
    # interface number would be missing without this line
    lines = rhd.udev_rule_for(0x3434).split("\n")
    assert lines[0] == ('SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3434", '
                        'ENV{ID_USB_INTERFACE_NUM}=="", IMPORT{builtin}="usb_id"')
    assert all('ENV{ID_USB_INTERFACE_NUM}=="04"' in line for line in lines[1:])

def test_udev_rule_without_interface_has_no_interface_match():
    rule = rhd.udev_rule_for(0x1532)
    assert "ID_USB_INTERFACE_NUM" not in rule
    assert "IMPORT" not in rule
    assert 'ATTRS{idProduct}=="0574"' in rule

def test_udev_rule_for_unknown_vendor_stays_vendor_wide():
    assert rhd.udev_rule_for(0xABCD) == (
        'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="abcd", '
        'MODE="0660", TAG+="uaccess", TAG+="udev-acl"'
    )

def test_udev_unblock_command_triggers_only_hidraw_devices():
    cmd = rhd.udev_unblock_command(0x3434)
    assert cmd.endswith("sudo udevadm control --reload-rules && "
                        "sudo udevadm trigger --subsystem-match=hidraw"), cmd

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
            {"name": "Glorious Model O Wireless", "serial": "sim-glorious-model-o", "blocked": True, "vid": "258a", "pid": "2022",
             "unblock_command": rhd.udev_unblock_command(0x258a), "deviceType": "mouse"},
        ]

def test_simulate_m5_reports_after_its_rule():
    with simulate_env() as sim_dir:
        with open(os.path.join(sim_dir, "70-batterywatch-hid-3434.rules"), "w") as f:
            f.write(rhd.UDEV_HEADER + "\n" + rhd.udev_rule_for(0x3434) + "\n")
        assert json.loads(run_main_capture()) == [
            {"name": "Keychron M5", "serial": "sim-keychron-m5", "percentage": 88, "charging": False, "deviceType": "mouse"},
            {"name": "Steam Controller 2", "serial": "sim-steam-controller-2", "blocked": True, "vid": "28de", "pid": "1304",
             "unblock_command": rhd.udev_unblock_command(0x28de), "deviceType": "gamepad"},
            {"name": "Glorious Model O Wireless", "serial": "sim-glorious-model-o", "blocked": True, "vid": "258a", "pid": "2022",
             "unblock_command": rhd.udev_unblock_command(0x258a), "deviceType": "mouse"},
        ]

def test_simulate_both_report_after_both_rules():
    with simulate_env() as sim_dir:
        for vid in (0x3434, 0x28de):
            with open(os.path.join(sim_dir, rhd.udev_rule_path(vid).rsplit("/", 1)[1]), "w") as f:
                f.write(rhd.UDEV_HEADER + "\n" + rhd.udev_rule_for(vid) + "\n")
        assert json.loads(run_main_capture()) == [
            {"name": "Keychron M5", "serial": "sim-keychron-m5", "percentage": 88, "charging": False, "deviceType": "mouse"},
            {"name": "Steam Controller 2", "serial": "sim-steam-controller-2", "percentage": 85, "charging": True, "deviceType": "gamepad"},
            {"name": "Glorious Model O Wireless", "serial": "sim-glorious-model-o", "blocked": True, "vid": "258a", "pid": "2022",
             "unblock_command": rhd.udev_unblock_command(0x258a), "deviceType": "mouse"},
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
# Glorious (feature-report transport)
# ══════════════════════════════════════════════════════════════════════════
def test_glorious_reads_battery_over_feature_reports():
    install_glorious_scenario()
    set_glorious_reply(pct=42)
    devs = rhd.find_devices()
    assert len(devs) == 1, f"one entry per physical mouse, got {devs!r}"
    dev = devs[0]
    assert dev.devpath == "/dev/hidraw2", f"vendor usage-page node targeted, got {dev.devpath}"
    assert dev.desc.name == "Glorious Model O Wireless", dev.desc.name

    assert rhd.read_status(dev) == {"percentage": 42, "charging": None}

    # exchange is SET_FEATURE then GET_FEATURE on the interrupt-free path
    nrs = [req & 0xFF for _fd, req, _b in scenario["ioctls"]]
    assert nrs == [0x06, 0x07], f"SET then GET feature, got {nrs!r}"
    assert scenario["ioctls"][0][2] == rhd.GLORIOUS_REQUEST, "request packet sent verbatim"
    assert scenario["ioctls"][0][2][3] == 0x02 and scenario["ioctls"][0][2][6] == 0x83
    assert scenario["writes"] == [], "feature transport writes nothing to the endpoint"
    assert scenario["reads"] == [], "feature transport reads nothing from the endpoint"
    assert scenario["open_flags"] and all(f & os.O_RDWR for f in scenario["open_flags"]), \
        "feature reports need the node opened read-write"

def test_glorious_zero_percent_floors_at_one():
    install_glorious_scenario()
    set_glorious_reply(pct=0)
    dev = rhd.find_devices()[0]
    assert rhd.read_status(dev) == {"percentage": 1, "charging": None}

def test_glorious_asleep_and_bad_echo_report_nothing():
    for state, cmd, why in ((0xA4, 0x83, "asleep"), (0xA0, 0x83, "waking up"), (0xA1, 0x00, "not a battery reply")):
        install_glorious_scenario()
        set_glorious_reply(pct=42, state=state, cmd=cmd)
        dev = rhd.find_devices()[0]
        assert rhd.read_status(dev) is None, f"{why} -> no reading"

def test_glorious_matches_any_vendor_usage_page():
    # The exact vendor page differs per model; the reference implementation
    # ranks pages rather than filtering, so any 0xffxx page must match.
    for page in (0xFF01, 0xFF00, 0xFF02, 0xFFA0):
        install_glorious_scenario(pid="00002034", usage_page=page)  # Model D 2 PRO dongle
        set_glorious_reply(pct=77)
        devs = rhd.find_devices()
        assert len(devs) == 1, f"page {page:#06x}: expected a match, got {devs!r}"
        assert devs[0].desc.name == "Glorious Model D 2 PRO", devs[0].desc.name
        assert rhd.read_status(devs[0]) == {"percentage": 77, "charging": None}

def test_glorious_non_vendor_pages_are_ignored():
    install_glorious_scenario(usage_page=0x0C)  # consumer-control collection
    assert rhd.find_devices() == [], "a non-vendor collection carries no battery"

def test_glorious_prefers_the_best_ranked_vendor_node():
    # Both nodes of the same physical mouse expose a vendor page; 0xff01 wins
    # over 0xff00, matching the reference's interface scoring.
    install_glorious_scenario()
    scenario["descriptors"] = {"hidraw1": hid_descriptor(0xFF01), "hidraw2": hid_descriptor(0xFF00)}
    devs = rhd.find_devices()
    assert len(devs) == 1, f"still one physical mouse, got {devs!r}"
    assert devs[0].devpath == "/dev/hidraw1", f"0xff01 outranks 0xff00, got {devs[0].devpath}"

def test_glorious_blocked_reports_udev_rule_with_write_access():
    install_glorious_scenario(with_blocked=True)
    with sandboxed_rules():
        entries = json.loads(run_main_capture())
    assert len(entries) == 1 and entries[0]["blocked"] is True, entries
    assert entries[0]["vid"] == "258a" and entries[0]["pid"] == "2022", entries
    assert entries[0]["deviceType"] == "mouse", entries
    rule = rhd.udev_rule_for(0x258A)
    assert 'MODE="0660"' in rule, "feature reports need write access in the udev rule"
    assert 'ATTRS{idProduct}=="2022"' in rule and 'ATTRS{idProduct}=="201a"' in rule, rule


def test_glorious_real_model_o_wireless_node_layout():
    # Node layout captured from real hardware (258a:2022, diagnose.py): three
    # interfaces, none declaring 0xff01/0xff00 - the vendor collection sits on
    # 0xffa0/0xffff. All three answer the battery query; iface 2 is the
    # best-ranked vendor node and must be the one picked.
    install_glorious_scenario()
    scenario["uevents"] = {
        f"hidraw{n}": ("DRIVER=hid-generic\nHID_ID=0003:0000258A:00002022\n"
                       "HID_NAME=Glorious Model O Wireless\n"
                       f"HID_PHYS=usb-0000:02:00.0-1/input{n}\nHID_UNIQ=000000000000\n")
        for n in (0, 1, 2)
    }
    scenario["fake_devs"] = {f"/dev/hidraw{n}": 400 + n for n in (0, 1, 2)}
    scenario["descriptors"] = {
        "hidraw0": hid_descriptor_pages(0x01, 0x02, 0x09, 0x0C),
        "hidraw1": hid_descriptor_pages(0x01, 0x07, 0x08, 0x0C, 0xFFA0, 0xFFFF),
        "hidraw2": hid_descriptor_pages(0xFFFF),
    }
    scenario["reply_fd"] = 402
    set_glorious_reply(pct=0x5D)  # the byte the real mouse returned

    devs = rhd.find_devices()
    assert len(devs) == 1, f"one entry for the mouse, got {devs!r}"
    assert devs[0].devpath == "/dev/hidraw2", f"best-ranked vendor node, got {devs[0].devpath}"
    # all-zero HID_UNIQ is treated as absent, so the physical path identifies it
    assert devs[0].serial == "usb-0000:02:00.0-1", devs[0].serial
    assert rhd.read_status(devs[0]) == {"percentage": 93, "charging": None}


def test_feature_reply_requires_nine_bytes_but_not_the_full_buffer():
    for length in (0, 6, 8, 9, 64, 65):
        install_glorious_scenario()
        set_glorious_reply(pct=42)
        scenario["reply_buf"] = scenario["reply_buf"][:length]
        result = rhd.read_status(rhd.find_devices()[0])
        assert result == ({"percentage": 42, "charging": None} if length >= 9 else None), length


def test_generic_schema_without_charging_data_reports_unknown():
    schema = rhd.InputStreamSchema(rhd.DataPos(0, 1), None, None)
    assert rhd.interpret(schema, {0: b"\x00\x2a"}) == {"percentage": 42, "charging": None}


def test_usb_serial_rejects_an_all_zero_string():
    with tempfile.TemporaryDirectory() as directory:
        hid_dir = os.path.join(directory, "usb", "1-3", "1-3:1.1", "hid")
        usb_dir = os.path.dirname(os.path.dirname(hid_dir))
        os.makedirs(hid_dir)
        for name, value in (("idVendor", "258a"), ("idProduct", "2022"), ("serial", "000000000000")):
            with open(os.path.join(usb_dir, name), "w") as file:
                file.write(value)
        assert unpatched_usb_serial(os.path.join(hid_dir, "uevent"), 0x258A, 0x2022) is None


def test_feature_ioctl_failures_close_the_descriptor_and_preserve_other_devices():
    import errno
    for operation in (0x06, 0x07):
        for error in (errno.EINVAL, errno.EIO):
            install_glorious_scenario()
            closed = []
            def failing_ioctl(fd, request, buf):
                if request & 0xFF == operation:
                    raise OSError(error, "test ioctl failure")
                return fake_ioctl(fd, request, buf)
            with mock.patch.object(rhd.fcntl, "ioctl", failing_ioctl), \
                    mock.patch.object(rhd.os, "close", closed.append):
                assert json.loads(run_main_capture()) == []
            assert 402 in closed
            if operation == 0x06:
                assert scenario["ioctls"] == [], "GET must not follow a failed SET"
            install_m5_scenario()
            set_m5_reply(87)
            assert json.loads(run_main_capture())[0]["percentage"] == 87


def test_short_feature_request_does_not_send_get():
    install_glorious_scenario()
    with mock.patch.object(rhd.fcntl, "ioctl", return_value=8) as ioctl:
        assert rhd.read_status(rhd.find_devices()[0]) is None
    assert ioctl.call_count == 1


def test_feature_schema_never_writes_an_output_report():
    install_glorious_scenario()
    dev = rhd.find_devices()[0]
    assert rhd.open_device(dev, dev.source) == 402
    assert scenario["writes"] == []


def test_glorious_charging_is_unknown_for_wireless_and_wired_variants():
    for model in rhd.KNOWN_DEVICES:
        if model.parse is not rhd._glorious_parse:
            continue
        for variant in model.variants:
            dev = rhd.FoundDevice("/dev/test", "test", model, variant.pid, model.source)
            buf = bytearray(9)
            buf[1], buf[6], buf[8] = 0xA1, 0x83, 20
            with mock.patch.object(rhd, "_feature_exchange", return_value=bytes(buf)):
                assert rhd._device_entry(dev)["charging"] is None


def test_glorious_serial_rejects_zero_usb_and_hid_serials():
    install_glorious_scenario()
    for usb, hid, expected in (("000000000000", "000000000000", "usb-0000:00:14.0-3"),
                               ("USB-SERIAL", "000000000000", "USB-SERIAL"),
                               (None, "HID-SERIAL", "HID-SERIAL")):
        scenario["uevents"] = {name: re.sub(r"HID_UNIQ=.*", f"HID_UNIQ={hid}", text)
                              for name, text in scenario["uevents"].items()}
        with mock.patch.object(rhd, "usb_serial", return_value=usb):
            assert rhd.find_devices()[0].serial == expected


def test_razer_uses_the_same_node_ranking_as_glorious():
    for first_pages, second_pages, expected in (
        ((0xFF14,), (0xFF14,), "/dev/hidraw6"),
        ((0xFF14,), (0xFF14, 0xFF00), "/dev/hidraw6"),
        ((0xFF14, 0xFF00), (0xFF14, 0xFF01), "/dev/hidraw6"),
        ((0xFF14, 0xFF01), (0xFF14, 0xFF00), "/dev/hidraw5"),
    ):
        for reverse in (False, True):
            install_razer_scenario()
            original = scenario["uevents"]["hidraw5"]
            scenario["uevents"]["hidraw6"] = original.replace("input3", "input9")
            scenario["descriptors"] = {
                "hidraw5": hid_descriptor_pages(*first_pages),
                "hidraw6": hid_descriptor_pages(*second_pages),
            }
            if reverse:
                scenario["uevents"] = dict(reversed(list(scenario["uevents"].items())))
            assert rhd.find_devices()[0].devpath == expected, (first_pages, second_pages, reverse)


def test_discovery_keeps_more_than_eight_devices_in_stable_order():
    install_glorious_scenario()
    template = scenario["uevents"]["hidraw2"]
    scenario["uevents"] = {f"hidraw{n}": template.replace("-3/input1", f"-{n + 10}/input1")
                          for n in reversed(range(12))}
    scenario["descriptors"] = {name: hid_descriptor(0xFF01) for name in scenario["uevents"]}
    devs = rhd.find_devices()
    assert len(devs) == 12
    assert [d.serial for d in devs] == sorted(d.serial for d in devs)


def test_losing_node_does_not_resolve_its_serial():
    install_glorious_scenario()
    scenario["descriptors"]["hidraw1"] = hid_descriptor(0xFF01)
    scenario["descriptors"]["hidraw2"] = hid_descriptor(0xFF00)
    with mock.patch.object(rhd, "usb_serial", return_value=None) as resolver:
        assert rhd.find_devices()[0].devpath == "/dev/hidraw1"
    assert resolver.call_count == 1


def test_import_does_not_replace_shared_stdlib_functions():
    assert (os.open, os.read, os.write, os.close, os.listdir, select.poll, fcntl.ioctl, time.sleep) == (
        real_osopen, real_osread, real_oswrite, real_osclose, real_listdir, real_poll, real_ioctl, real_sleep)
    fd = os.open(os.devnull, os.O_RDONLY, dir_fd=None)
    os.close(fd)


# Launch the actual feature worker with its ioctl replaced inside that child.
# Mode selects a normal reply or a blocking SET/GET without needing HID hardware.
FEATURE_WORKER = r'''
import sys, time
mode = sys.argv.pop(1)
sys.argv = sys.argv[1:]
namespace = {"__file__": sys.argv[0], "__name__": "feature_test"}
with open(sys.argv[0]) as source:
    exec(compile(source.read(), sys.argv[0], "exec"), namespace)
def ioctl(fd, request, buf):
    operation = request & 255
    if (mode == "set" and operation == 6) or (mode == "get" and operation == 7):
        time.sleep(30)
    if operation == 7:
        buf[1], buf[6], buf[8] = 0xA1, 0x83, 42
    return len(buf)
namespace["fcntl"].ioctl = ioctl
namespace["main"]()
'''


def feature_popen(mode):
    def launch(command, **kwargs):
        return subprocess.Popen([command[0], "-c", FEATURE_WORKER, mode, *command[1:]], **kwargs)
    return launch


def test_feature_subprocess_preserves_report_bytes_and_errors():
    install_glorious_scenario()
    dev = rhd.find_devices()[0]._replace(devpath=os.devnull)
    with mock.patch.object(rhd, "_feature_exchange", unpatched_feature_exchange), \
            mock.patch.object(rhd, "subprocess", types.SimpleNamespace(
                **{**vars(subprocess), "Popen": feature_popen("reply")})):
        assert rhd.read_status(dev) == {"percentage": 42, "charging": None}
        assert rhd.read_status(dev._replace(devpath="/nonexistent-batterywatch-device")) is None


def test_feature_timeout_does_not_wait_for_worker_exit_or_pipe_eof():
    install_glorious_scenario()
    dev = rhd.find_devices()[0]
    release = threading.Event()
    reaping = threading.Event()
    finished = threading.Event()
    class PendingWorker:
        killed = False
        def communicate(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("feature worker", timeout)
            reaping.set()
            release.wait(3)
            finished.set()
            return b"", b""
        def kill(self):
            self.killed = True
    process = PendingWorker()
    try:
        with mock.patch.object(rhd, "_feature_exchange", unpatched_feature_exchange), \
                mock.patch.object(rhd, "subprocess", types.SimpleNamespace(
                    **{**vars(subprocess), "Popen": lambda *args, **kwargs: process})):
            assert rhd.read_status(dev) is None
            assert process.killed
            assert reaping.wait(1)
            assert not finished.is_set(), "reader waited for the pending kernel operation"
    finally:
        release.set()
        assert finished.wait(1)


def test_feature_timeout_delivers_other_device_json_and_exits():
    # Exercise the complete helper lifetime, not just a thread join. Its stdout
    # must close while an isolated device's SET or GET is still blocked.
    driver = r'''
import importlib.util, sys, types
spec = importlib.util.spec_from_file_location("hidtests", sys.argv[1])
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
rhd = t.rhd
t.install_glorious_scenario()
feature = rhd.find_devices()[0]._replace(devpath=t.os.devnull)
feature = feature._replace(source=feature.source._replace(timeout=0.15, settle=0))
t.install_m5_scenario()
t.set_m5_reply(87)
mouse = rhd.find_devices()[0]
rhd.find_devices = lambda: [feature, mouse]
rhd._feature_exchange = t.unpatched_feature_exchange
rhd.subprocess = types.SimpleNamespace(**{**vars(t.subprocess), "Popen": t.feature_popen(sys.argv[2])})
rhd._DEBUG = True
sys.argv = ["read_hid_devices", "--debug"]
rhd.main()
'''
    for operation in ("set", "get"):
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-c", driver, __file__, operation],
                                capture_output=True, text=True, timeout=3)
        assert result.returncode == 0, result.stderr
        assert time.monotonic() - started < 2
        entries = json.loads(result.stdout)
        assert len(entries) == 1 and entries[0]["percentage"] == 87, entries
        assert "feature report timed out after 0.15s" in result.stderr


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

def test_debug_output_explains_a_silent_glorious_mouse():
    # an asleep mouse is dropped without a reading; the log shows why
    install_glorious_scenario()
    set_glorious_reply(pct=42, state=0xA4)
    with debug_stderr() as stderr:
        assert rhd.read_status(rhd.find_devices()[0]) is None
    log = stderr.getvalue()
    assert "set feature 00 00 00 02 02 00 83" in log, "request bytes"
    assert "received 00 a4" in log, "reply bytes with the asleep link state"
    assert "reading None" in log, log


# ══════════════════════════════════════════════════════════════════════════
# Helper as a subprocess (real run, no device)
# ══════════════════════════════════════════════════════════════════════════
def test_helper_compiles():
    assert py_compile.compile(HELPER, doraise=True) is not None

def test_helper_real_run_emits_valid_json():
    r = subprocess.run([sys.executable, HELPER], capture_output=True, text=True,
                       cwd=os.path.dirname(HELPER), timeout=30)
    assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr!r}"
    parsed = json.loads(r.stdout.strip())
    assert isinstance(parsed, list), f"stdout={r.stdout.strip()!r}"

def test_debug_flag_keeps_stdout_valid_json():
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
