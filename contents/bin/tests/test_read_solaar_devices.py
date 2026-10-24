#!/usr/bin/env python3
"""
test_read_solaar_devices.py - self-check for the Solaar helper WITHOUT Solaar
and WITHOUT Logitech hardware.

Loads the real contents/bin/read_solaar_devices script as a module (like
test_read_hid_devices does) and exercises every behavior the widget depends
on, against fakes that mimic Solaar's logitech_receiver API surface:

  Mapping:     kind->deviceType, level->percentage, status->charging
  Iteration:   receiver paired-device walk, offline/no-battery drops,
               direct-USB and Bluetooth devices, serial fallbacks, dedupe
  Permission:  create errors and unopenable nodes become blocked entries with
               the exact unblock command; permission-less runs collapse into
               one blocked marker
  Robustness:  receiver walk failures never kill the run; handles are closed
  CLI:         --simulate (blocked until the rule exists), stdout stays valid
               JSON because the error path is also a JSON object

Written as plain test_*() functions so they read like idiomatic Python tests;
runs under pytest AND standalone via the tiny runner at the bottom, so no
dependencies are needed.

Run:  python3 contents/bin/tests/test_read_solaar_devices.py
  or: pytest contents/bin/tests/test_read_solaar_devices.py
Exit: 0 = all checks passed, 1 = at least one failed.
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, ".."))
HELPER = os.path.join(BIN, "read_solaar_devices")


def load_helper():
    # Load the real contents/bin/read_solaar_devices script as module "rsd", so
    # the tests exercise the same code the widget runs. The file has no .py
    # suffix, so the loader is specified explicitly.
    loader = importlib.machinery.SourceFileLoader("rsd", HELPER)
    spec = importlib.util.spec_from_loader("rsd", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rsd"] = mod
    loader.exec_module(mod)
    return mod


rsd = load_helper()


# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═
# Solaar API fakes: only the attributes/behaviors the helper actually touches
# ══════════════════════════════════════════════════════════════════════════════

class FakeKind(int):
    """Mimics Solaar's NamedInt kind (int subclass with a name)."""

    def __new__(cls, value, name):
        obj = int.__new__(cls, value)
        obj.name = name
        return obj

    def __str__(self):
        return self.name


class FakeStatus(int):
    """Mimics Solaar's BatteryStatus flag values."""

    @property
    def value(self):
        return int(self)


class FakeBattery:
    """Mimics Solaar's Battery: level plus the upstream charging() method."""

    def __init__(self, level, status):
        self.level = level
        self.status = status

    def charging(self):
        # Upstream semantics: RECHARGING, ALMOST_FULL, FULL, SLOW_RECHARGE
        return self.status is not None and int(getattr(self.status, "value", self.status)) in (1, 2, 3, 4)


class FakeDevice:
    instances = []
    closed = 0

    def __init__(self, name="MX Master 3", serial="cd7d85a0", kind=None, status=None,
                 level=72, ping=True, battery=True, raise_battery=None, hid_serial=None,
                 unitId=None, wpid=None, path=None, number=1):
        self.name = name
        self.serial = serial
        self.kind = kind
        self.status = status
        self.level = level
        self.answer_ping = ping
        self.has_battery = battery
        self.raise_battery = raise_battery
        self.hid_serial = hid_serial
        self.unitId = unitId
        self.wpid = wpid
        self.path = path
        self.number = number
        FakeDevice.instances.append(self)

    def ping(self):
        if self.answer_ping is True:
            return True
        if self.answer_ping is False:
            return False
        raise self.answer_ping  # an exception object: ping fails

    def battery(self):
        if self.raise_battery is not None:
            raise self.raise_battery
        if not self.has_battery:
            return None
        return FakeBattery(self.level, self.status)

    def close(self):
        FakeDevice.closed += 1
        FakeDevice.instances.remove(self)


def make_modules(devices, infos, create_raises=None, paired=None):
    """rsd._Modules assembled from fake receiver/device/base triples.

    `paired` sets the devices a created receiver walks (defaults to the
    flat `devices` list), so receiver-paired and directly connected devices
    can be supplied separately.
    """
    paired = devices if paired is None else paired
    raise_error = create_raises

    class FakeBase:
        @staticmethod
        def receivers_and_devices():
            yield from infos

    class FakeDeviceModule:
        Device = FakeDevice

        @staticmethod
        def create_device(mod_base, info):
            if raise_error:
                raise raise_error
            for dev in devices:
                if getattr(dev, "path", None) == info.path:
                    return dev
            return None

        @staticmethod
        def create_centurion_receiver(mod_base, info):
            if raise_error:
                raise raise_error
            return None

    class FakeReceiver:
        def __init__(self):
            self.paired = paired

        def count(self):
            return len(self.paired)

        def __iter__(self):
            yield from self.paired

        @staticmethod
        def close():
            for dev in paired:
                dev.close()

    class FakeReceiverModule:
        Receiver = FakeReceiver

        @staticmethod
        def create_receiver(mod_base, info):
            if raise_error:
                raise raise_error
            return FakeReceiver()

    return rsd._Modules(FakeBase(), FakeDeviceModule(), FakeReceiverModule())


# ══════════════════════════════════════════════════════════════════════════════
# Mapping: kind -> deviceType
# ══════════════════════════════════════════════════════════════════════════════

def test_kind_named_int_maps_to_widget_type():
    assert rsd.device_type(FakeKind(2, "mouse")) == "mouse"
    assert rsd.device_type(FakeKind(1, "keyboard")) == "keyboard"
    # headset kinds pass through to the widget's headset type
    assert rsd.device_type(FakeKind(13, "headset")) == "audio-headset"
    assert rsd.device_type(FakeKind(9, "touchpad")) == "touchpad"
    # trackball maps to touchpad for the widget's icon set
    assert rsd.device_type(FakeKind(5, "trackball")) == "touchpad"
    # numpad is a keyboard flavor
    assert rsd.device_type(FakeKind(2, "numpad")) == "keyboard"


def test_kind_unknown_and_none_fall_back():
    assert rsd.device_type(None) is None
    assert rsd.device_type(FakeKind(0, "unknown")) is None
    assert rsd.device_type(FakeKind(6, "presenter")) is None
    assert rsd.device_type("?") is None
    # a plain string kind (defensive) still maps when known
    assert rsd.device_type("mouse") == "mouse"


# ══════════════════════════════════════════════════════════════════════════════
# Mapping: level -> percentage
# ══════════════════════════════════════════════════════════════════════════════

def test_percentage_exact_levels():
    assert rsd.percentage(88) == 88
    assert rsd.percentage(0) == 0


def test_percentage_approximation_levels_are_upstream_values():
    # Solaar's approximation ints (BatteryLevelApproximation) are already the
    # percentages Solaar displays: good=50, full=90...
    assert rsd.percentage(FakeKind(50, "GOOD")) == 50
    assert rsd.percentage(FakeKind(90, "FULL")) == 90
    assert rsd.percentage(FakeKind(20, "LOW")) == 20


def test_percentage_clamps_and_nones():
    assert rsd.percentage(150) == 100
    assert rsd.percentage(-5) == 0
    assert rsd.percentage(None) is None


# ══════════════════════════════════════════════════════════════════════════════
# Mapping: status -> charging
# ══════════════════════════════════════════════════════════════════════════════

def test_device_entry_uses_upstream_charging():
    # charging comes straight from Solaar's Battery.charging(); the fake
    # mirrors its semantics (RECHARGING=1, ALMOST_FULL=2, FULL=3,
    # SLOW_RECHARGE=4 charge; DISCHARGING=0, INVALID=5, THERMAL=6 do not)
    dev = FakeDevice(status=FakeStatus(1), level=40)
    assert rsd.device_entry(dev)["charging"] is True
    dev = FakeDevice(status=FakeStatus(3), level=40)
    assert rsd.device_entry(dev)["charging"] is True
    dev = FakeDevice(status=FakeStatus(0), level=40)
    assert rsd.device_entry(dev)["charging"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Device entries
# ══════════════════════════════════════════════════════════════════════════════

def test_device_entry_happy_path():
    dev = FakeDevice(kind=FakeKind(2, "mouse"), status=FakeStatus(0), level=72,
                     hid_serial=None, unitId="4066-C535", path="/dev/hidraw5")
    entry = rsd.device_entry(dev)
    assert entry == {
        "name": "MX Master 3",
        "serial": "cd7d85a0",
        "percentage": 72,
        "charging": False,
        "deviceType": "mouse",
        "unitId": "4066-C535",
        "connectionType": 1,
        "bluetooth_address": None,
    }


def test_device_entry_serial_fallbacks():
    dev = FakeDevice(serial=None, hid_serial="aa:bb:cc:dd:ee:ff", unitId=None, path=None)
    assert rsd.device_entry(dev)["serial"] == "aa:bb:cc:dd:ee:ff"
    dev = FakeDevice(serial=None, hid_serial=None, unitId="12345678", path="/dev/hidraw2")
    assert rsd.device_entry(dev)["serial"] == "12345678"
    dev = FakeDevice(serial=None, hid_serial=None, unitId=None, path="/dev/hidraw3")
    assert rsd.device_entry(dev)["serial"] == "MX Master 3 (/dev/hidraw3)"


def test_device_entry_charging_flag():
    dev = FakeDevice(status=FakeStatus(1), level=40)
    assert rsd.device_entry(dev)["charging"] is True
    dev = FakeDevice(status=FakeStatus(0), level=40)
    assert rsd.device_entry(dev)["charging"] is False
    dev = FakeDevice(status=FakeStatus(5), level=40)  # INVALID_BATTERY: not charging
    assert rsd.device_entry(dev)["charging"] is False


def test_device_entry_drops_offline_and_broken():
    assert rsd.device_entry(FakeDevice(ping=False)) is None
    assert rsd.device_entry(FakeDevice(ping=RuntimeError("gone"))) is None
    assert rsd.device_entry(FakeDevice(battery=False)) is None          # no battery feature
    assert rsd.device_entry(FakeDevice(level=None)) is None            # battery without level
    assert rsd.device_entry(FakeDevice(raise_battery=OSError("busy"))) is None


def test_device_entry_drops_without_readable_level():
    # battery.level None means no percentage (e.g. charging notifications
    # without level info) - nothing to show, drop until the next poll
    assert rsd.device_entry(FakeDevice(level=None, status=FakeStatus(1))) is None


def test_device_entry_raises_do_not_discard_read_values():
    # kind is a lazy property that does HID++ I/O; when it raises on a
    # descriptor-less 2.0 device, the serial read BEFORE it must survive -
    # silently losing it would change the widget's dedupe/hide key.
    class KindRaisesDevice(FakeDevice):
        @property
        def kind(self):
            raise OSError("device is asleep")

        @kind.setter
        def kind(self, value):
            pass  # tolerate the base __init__'s assignment

    dev = KindRaisesDevice(serial="4066-C535", hid_serial="aa:bb:cc:dd:ee:ff",
                           unitId=None, level=70)
    entry = rsd.device_entry(dev)
    assert entry["serial"] == "4066-C535"      # the already-read identity kept
    assert entry["deviceType"] is None         # kind failed -> widget fallback
    assert entry["unitId"] is None


# ══════════════════════════════════════════════════════════════════════════════
# collect(): receiver walks, direct devices, dedupe, blocked markers
# ══════════════════════════════════════════════════════════════════════════════
RECV_INFO = types.SimpleNamespace(path="/dev/hidrecv", isDevice=False, centurion=False)


def test_collect_receiver_paired_device():
    FakeDevice.closed = 0  # reset before construction: collect() must close everything
    modules = make_modules([FakeDevice(path="/dev/hidrecv", kind=FakeKind(1, "keyboard"), level=55)], [RECV_INFO])
    entries = rsd.collect(modules)
    assert [(e["name"], e["percentage"], e["deviceType"]) for e in entries] == [
        ("MX Master 3", 55, "keyboard")]
    # handle opening is released after the run
    assert FakeDevice.closed >= 1 and FakeDevice.instances == []


def test_collect_direct_bluetooth_device():
    info = types.SimpleNamespace(path="/dev/hidbt", isDevice=True, centurion=False)
    dev = FakeDevice(path="/dev/hidbt", serial=None, hid_serial="cb:6a:b2:6c:73:47", kind=FakeKind(2, "mouse"))
    dev.bluetooth = True
    modules = make_modules([dev], [info])
    entries = rsd.collect(modules)
    assert len(entries) == 1
    assert entries[0]["serial"] == "cb:6a:b2:6c:73:47"
    # Bluetooth devices keep the widget's disconnect action: explicit type + MAC
    assert entries[0]["connectionType"] == 2
    assert entries[0]["bluetooth_address"] == "cb:6a:b2:6c:73:47"


def test_collect_dedupes_same_serial():
    infos = [
        types.SimpleNamespace(path="/dev/hidrawA", isDevice=True, centurion=False),
        types.SimpleNamespace(path="/dev/hidrawB", isDevice=True, centurion=False),
    ]
    # one physical device exposed via two hidraw interfaces
    dev_a = FakeDevice(path="/dev/hidrawA", serial="same-serial")
    dev_b = FakeDevice(path="/dev/hidrawB", serial="same-serial")
    modules = make_modules([dev_a, dev_b], infos)
    entries = rsd.collect(modules)
    assert len(entries) == 1
    assert entries[0]["serial"] == "same-serial"


def test_collect_multipoint_dedupes_by_unit_id_prefers_bluetooth():
    # A device reachable over several transports at once (multipoint: paired
    # to a receiver AND connected via Bluetooth) carries different identity
    # strings per transport (HID++ serial vs BT MAC) but the same unique
    # unitId - it must be reported once, as the Bluetooth instance.
    bt_info = types.SimpleNamespace(path="/dev/hidbt", isDevice=True, centurion=False)

    paired = FakeDevice(path="/dev/hidrecv", serial="hidpp-serial", unitId="E4B786D0",
                        kind=FakeKind(2, "mouse"), level=60)
    paired.hid_serial = None
    bt_dev = FakeDevice(path="/dev/hidbt", serial=None, unitId="E4B786D0",
                        hid_serial="cb:6a:b2:6c:73:47", kind=FakeKind(2, "mouse"), level=50)
    bt_dev.bluetooth = True

    # infos order mirrors enumeration: receiver first, BT second
    modules = make_modules([bt_dev], [RECV_INFO, bt_info], paired=[paired])
    entries = rsd.collect(modules)
    assert len(entries) == 1
    assert entries[0]["serial"] == "cb:6a:b2:6c:73:47"  # the Bluetooth instance won
    assert entries[0]["connectionType"] == 2
    assert entries[0]["percentage"] == 50


def test_collect_generic_unit_ids_never_collapse_distinct_devices():
    # Solaar reports 00010000 for devices without a unique unit serial -
    # keying dedupe on it silently vanished every device but one. Both must
    # survive as distinct entries (this is the common case).
    infos = [
        types.SimpleNamespace(path="/dev/hidrawA", isDevice=True, centurion=False),
        types.SimpleNamespace(path="/dev/hidrawB", isDevice=True, centurion=False),
    ]
    m305 = FakeDevice(path="/dev/hidrawA", name="Wireless Mouse M305",
                      serial="f9-0d-4f-0c", unitId="00010000", level=60)
    mx = FakeDevice(path="/dev/hidrawB", name="MX Master 3", serial=None,
                    hid_serial="cb:6a:b2:6c:73:47", unitId="00010000", level=50)
    modules = make_modules([m305, mx], infos)
    entries = rsd.collect(modules)
    assert [e["serial"] for e in entries] == ["f9-0d-4f-0c", "cb:6a:b2:6c:73:47"]


def test_collect_receiver_walk_failure_still_reports_others():
    class ExplodingReceiver:
        def __iter__(self):
            raise OSError("receiver vanished")

    infos = [
        types.SimpleNamespace(path="/dev/hidrecv", isDevice=False, centurion=False),
        types.SimpleNamespace(path="/dev/hidrawX", isDevice=True, centurion=False),
    ]

    class FakeBase:
        @staticmethod
        def receivers_and_devices():
            yield from infos

    class FakeDeviceModule:
        Device = FakeDevice

        @staticmethod
        def create_device(_base, info):
            if info.path == "/dev/hidrawX":
                return FakeDevice(path="/dev/hidrawX", name="MX Keys S", kind=FakeKind(1, "keyboard"))
            return None

        @staticmethod
        def create_centurion_receiver(_base, info):
            return None

    class FakeReceiverModule:
        Receiver = ExplodingReceiver

        @staticmethod
        def create_receiver(_base, info):
            return ExplodingReceiver()

    FakeDevice.closed = 0
    FakeDevice.instances.clear()
    entries = rsd.collect(rsd._Modules(FakeBase(), FakeDeviceModule(), FakeReceiverModule()))
    # the exploding receiver is dropped, the direct device is still reported
    assert [(e["name"], e["deviceType"]) for e in entries] == [("MX Keys S", "keyboard")]


class _LazyLevelBattery:
    """Battery whose lazy level read fails, like a HID++ timeout."""

    def charging(self):
        return False

    @property
    def level(self):
        raise RuntimeError("HID++ read timeout on feature 0x1000")


class _LazyLevelDevice(FakeDevice):
    def battery(self):
        return _LazyLevelBattery()


def test_collect_lazy_level_failure_keeps_the_other_direct_devices():
    # a raising lazy level read must not escape device_entry and empty the run
    infos = [
        types.SimpleNamespace(path="/dev/hidrawA", isDevice=True, centurion=False),
        types.SimpleNamespace(path="/dev/hidrawB", isDevice=True, centurion=False),
        types.SimpleNamespace(path="/dev/hidrawC", isDevice=True, centurion=False),
    ]
    first = FakeDevice(path="/dev/hidrawA", name="M305", serial="SER-A", level=55)
    broken = _LazyLevelDevice(path="/dev/hidrawB", name="G733", serial="SER-B")
    last = FakeDevice(path="/dev/hidrawC", name="MX Master 3", serial="SER-C", level=100)
    entries = rsd.collect(make_modules([first, broken, last], infos))
    assert [e["name"] for e in entries] == ["M305", "MX Master 3"]


def test_collect_lazy_level_failure_keeps_the_rest_of_a_receiver_walk():
    # same on the receiver path: the rest of that receiver's walk must survive
    paired = [
        FakeDevice(name="M305", serial="SER-P1", level=55),
        _LazyLevelDevice(name="G733", serial="SER-P2"),
        FakeDevice(name="MX Master 3", serial="SER-P3", level=100),
    ]
    infos = [types.SimpleNamespace(path="/dev/hidrecv", isDevice=False, centurion=False)]
    entries = rsd.collect(make_modules([], infos, paired=paired))
    assert [e["name"] for e in entries] == ["M305", "MX Master 3"]


def test_collect_permission_error_is_a_blocked_entry():
    raise_work = PermissionError(13, "Permission denied")
    infos = [types.SimpleNamespace(path="/dev/hidrecv", isDevice=False, centurion=False)]
    modules = make_modules([], infos, create_raises=raise_work)
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(rsd, "UDEV_RULES_DIR", tmp):
            entries = rsd.collect(modules)
    assert len(entries) == 1
    assert entries[0]["blocked"] is True
    assert entries[0]["serial"] == "/dev/hidrecv"
    assert "sudo" in entries[0]["unblock_command"]
    assert "70-batterywatch-solaar.rules" in entries[0]["unblock_command"]


def test_collect_blocked_markers_collapse_into_one():
    raise_work = PermissionError(13, "Permission denied")
    infos = [
        types.SimpleNamespace(path="/dev/hidrecv1", isDevice=False, centurion=False),
        types.SimpleNamespace(path="/dev/hidrecv2", isDevice=False, centurion=False),
    ]
    modules = make_modules([], infos, create_raises=raise_work)
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(rsd, "UDEV_RULES_DIR", tmp):
            entries = rsd.collect(modules)
    # both receivers collapse into a single blocked marker: one market, one copy command
    assert len(entries) == 1
    assert entries[0]["blocked"] is True


def test_collect_creator_returns_none_with_unopenable_node_is_blocked():
    # Upstream swallows uid access into None; the probe detects the details.
    infos = [types.SimpleNamespace(path="/dev/hidrecv", isDevice=False, centurion=False)]

    def fake_open(path, flags, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    class NoDevice:
        @staticmethod
        def create_device(_base, info):
            return None

        class Device:
            instances = []

    class FakeBase:
        @staticmethod
        def receivers_and_devices():
            yield from infos

    modules = rsd._Modules(FakeBase(), NoDevice, types.SimpleNamespace(create_receiver=lambda *a: None))
    # The temporary directory is created BEFORE the patch and removed AFTER
    # it: patching the real os module must not overlap tempfile's own syscalls.
    tmpdir = tempfile.mkdtemp()
    try:
        with mock.patch.object(rsd.os, "open", fake_open):
            with mock.patch.object(rsd, "UDEV_RULES_DIR", tmpdir):
                entries = rsd.collect(modules)
    finally:
        import shutil as _shutil

        _shutil.rmtree(tmpdir, ignore_errors=True)
    assert len(entries) == 1
    assert entries[0]["blocked"] is True


def test_collect_creator_returns_none_with_openable_node_is_skipped():
    # create returned None but the node opens fine: not a permission issue,
    # simply nothing to report this run
    infos = [types.SimpleNamespace(path="/dev/hidrecv", isDevice=False, centurion=False)]

    def fake_open(path, flags, *args, **kwargs):
        # leak-free open of a real openable file
        fd = os.open(os.devnull, flags)
        os.close(fd)
        return fd

    class NoDevice:
        @staticmethod
        def create_device(_base, info):
            return None

        class Device:
            instances = []

    class FakeBase:
        @staticmethod
        def receivers_and_devices():
            yield from infos

    modules = rsd._Modules(FakeBase(), NoDevice, types.SimpleNamespace(create_receiver=lambda *a: None))
    tmpdir = tempfile.mkdtemp()
    try:
        with mock.patch.object(rsd.os, "open", fake_open):
            with mock.patch.object(rsd, "UDEV_RULES_DIR", tmpdir):
                entries = rsd.collect(modules)
    finally:
        import shutil as _shutil

        _shutil.rmtree(tmpdir, ignore_errors=True)
    assert entries == []


# ══════════════════════════════════════════════════════════════════════════════
# lib: shebang parsing + import fallback
# ══════════════════════════════════════════════════════════════════════════════

def test_shebang_python_direct_paths():
    assert rsd.parse_shebang_python("/usr/bin/python3") == "/usr/bin/python3"
    assert rsd.parse_shebang_python("/usr/bin/python") == "/usr/bin/python"
    assert rsd.parse_shebang_python("/home/u/.local/pipx/venvs/solaar/bin/python") == \
        "/home/u/.local/pipx/venvs/solaar/bin/python"
    assert rsd.parse_shebang_python("/usr/local/bin/python3.14") == "/usr/local/bin/python3.14"


def test_shebang_python_with_flags_and_spacing():
    assert rsd.parse_shebang_python("/usr/bin/python3 -u   ") == "/usr/bin/python3"
    assert rsd.parse_shebang_python("/usr/bin/python -I -s") == "/usr/bin/python"


def test_shebang_python_rejects_env_and_shims():
    # `/usr/bin/env python` resolves through PATH, not the Solaar venv
    assert rsd.parse_shebang_python("python3") is None
    assert rsd.parse_shebang_python("/usr/bin/env python3 -u") is None
    assert rsd.parse_shebang_python("/bin/sh") is None
    assert rsd.parse_shebang_python("") is None
    # python-looking but not python
    assert rsd.parse_shebang_python("/usr/bin/pythonista") is None
    # but a direct path handed through env is still a direct path
    assert rsd.parse_shebang_python("env -S /opt/pyvenv/bin/python") == "/opt/pyvenv/bin/python"


def test_solaar_launchers_prefers_path_and_dedups():
    with mock.patch.object(rsd.shutil, "which", lambda name: "/usr/bin/solaar"), \
            mock.patch.object(rsd.os.path, "isfile", lambda p: True):
        launchers = rsd.solaar_launchers()
    # PATH entry comes first and known-prefix duplicates of it are dropped
    assert launchers[0] == "/usr/bin/solaar"
    assert launchers.count("/usr/bin/solaar") == 1


def test_candidate_interpreters_tries_current_first():
    candidates = rsd.candidate_interpreters()
    assert candidates[0] == sys.executable


def test_discovery_dirs_honor_environment():
    # hardcoded ~/.local/share/pipx and ~/miniconda3 must yield to the env vars
    with mock.patch.dict(os.environ, {"PIPX_HOME": "/opt/pipx", "CONDA_PREFIX": "/opt/conda"},
                         clear=True):
        assert rsd.pipx_venvs_dir() == "/opt/pipx/venvs"
        assert "/opt/conda/bin" in rsd.conda_bin_dirs()
    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/xdg"}, clear=True):
        assert rsd.pipx_venvs_dir() == "/xdg/pipx/venvs"


def test_candidate_interpreters_keeps_distinct_venv_and_base():
    # A venv's bin/python is a symlink to the base interpreter: same realpath,
    # different site-packages. Dedup must key on the literal path or the very
    # interpreter that carries Solaar is discarded (the default pipx layout).
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "python3")
        with open(base, "w") as stream:
            stream.write("#!/bin/sh\n")
        venv_bin = os.path.join(tmp, "venv", "bin")
        os.makedirs(venv_bin)
        venv_python = os.path.join(venv_bin, "python")
        os.symlink(base, venv_python)

        with mock.patch.object(rsd.sys, "executable", venv_python), \
                mock.patch.object(rsd.shutil, "which",
                                  lambda name: base if name == "python3" else None), \
                mock.patch.object(rsd.glob, "glob", lambda pattern: []):
            candidates = rsd.candidate_interpreters()

    assert venv_python in candidates
    assert base in candidates  # not collapsed away by realpath


def test_load_modules_import_error_no_cli():
    with mock.patch.dict(sys.modules, {"logitech_receiver": None}), \
            mock.patch.object(rsd, "candidate_interpreters", lambda: [sys.executable]), \
            mock.patch.object(rsd, "cached_runner", lambda: None):
        try:
            rsd.load_modules()
        except rsd.SolaarNotImportable as e:
            assert "not importable" in str(e)
            assert "pip install" in str(e)  # the user-facing hint
        else:
            raise AssertionError("expected SolaarNotImportable")


def test_load_modules_reexec_guard_blocks_a_second_attempt():
    # the re-exec flag is set: the fallback interpreter will not be tried again
    with mock.patch.dict(sys.modules, {"logitech_receiver": None}), \
            mock.patch.object(rsd, "candidate_interpreters", lambda: ["/venv/python"]), \
            mock.patch.object(rsd, "imports_solaar", lambda python: True), \
            mock.patch.object(rsd.os.path, "isfile", lambda p: True), \
            mock.patch.object(rsd, "cached_runner", lambda: None), \
            mock.patch.dict(os.environ, {"_BW_READ_SOLAR_DEVICES_REEXEC": "1"}):
        try:
            rsd.load_modules()
        except rsd.SolaarNotImportable as e:
            assert "even by Solaar's own interpreter" in str(e)
        else:
            raise AssertionError("expected SolaarNotImportable")


def test_load_modules_reexecs_into_the_first_working_interpreter():
    captured = {}

    def fake_execve(path, argv, env):
        captured["path"] = path
        captured["env"] = env
        raise OSError("stop after the exec attempt")  # keep the test process alive

    with mock.patch.dict(sys.modules, {"logitech_receiver": None}), \
            mock.patch.object(rsd, "candidate_interpreters",
                              lambda: [sys.executable, "/venv/python"]), \
            mock.patch.object(rsd, "imports_solaar", lambda python: True), \
            mock.patch.object(rsd.os.path, "isfile", lambda p: True), \
            mock.patch.object(rsd.os, "execve", fake_execve), \
            mock.patch.object(rsd, "cached_runner", lambda: None), \
            mock.patch.dict(os.environ, {}, clear=True):
        try:
            rsd.load_modules()
        except rsd.SolaarNotImportable:
            pass

    # the current interpreter is skipped; the venv interpreter is used
    assert captured["path"] == "/venv/python"
    assert captured["env"][rsd.REEXEC_ENV] == "1"
    # discovery hops are not cache-created: no CACHED_ENV until proven good
    assert rsd.CACHED_ENV not in captured["env"]


# ══════════════════════════════════════════════════════════════════════════════
# runner cache: the single positive-only token that skips discovery/probes
# ══════════════════════════════════════════════════════════════════════════════

def test_runner_cache_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(rsd, "runner_cache_path",
                               lambda: os.path.join(tmp, "cache")):
            assert rsd.cached_runner() is None
            rsd.write_runner_cache("flatpak")
            assert rsd.cached_runner() == "flatpak"
            rsd.write_runner_cache(f"python:{sys.executable}")
            assert rsd.cached_runner() == f"python:{sys.executable}"


def test_runner_cache_ignores_empty_and_malformed():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(rsd, "runner_cache_path",
                               lambda: os.path.join(tmp, "cache")):
            with open(os.path.join(tmp, "cache"), "w") as stream:
                stream.write("garbage-token")
            assert rsd.cached_runner() is None
            with open(os.path.join(tmp, "cache"), "w") as stream:
                stream.write("python:")
            assert rsd.cached_runner() is None  # no path -> not a python runner


def test_runner_cache_forgets_a_stale_python_path():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(rsd, "runner_cache_path",
                               lambda: os.path.join(tmp, "cache")), \
                mock.patch.object(rsd.os.path, "isfile", lambda p: False):
            rsd.write_runner_cache(f"python:/not/there")
            assert rsd.cached_runner() is None


def test_runner_cache_prefers_xdg_runtime_dir():
    with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"},
                         clear=True), \
            mock.patch.object(rsd.os, "access", lambda p, m: True):
        assert rsd.runner_cache_path() == "/run/user/1000/batterywatch-solaar-runner"
    with mock.patch.dict(os.environ, {}, clear=True):
        assert rsd.runner_cache_path().endswith(".cache/batterywatch/batterywatch-solaar-runner")


def test_load_modules_uses_cached_interpreter_without_probing():
    captured = {}

    def fake_execve(path, argv, env):
        captured["path"] = path
        captured["env"] = env
        raise OSError("stop after the exec attempt")  # keep the test process alive

    with mock.patch.dict(sys.modules, {"logitech_receiver": None}), \
            mock.patch.object(rsd, "cached_runner", lambda: "python:/cached/python"), \
            mock.patch.object(rsd, "candidate_interpreters",
                              lambda: [sys.executable]), \
            mock.patch.object(rsd.os.path, "isfile", lambda p: True), \
            mock.patch.object(rsd.os, "execve", fake_execve):
        try:
            rsd.load_modules()
        except rsd.SolaarNotImportable:
            pass

    # the cached interpreter is re-exec'd into directly...
    assert captured["path"] == "/cached/python"
    assert captured["env"][rsd.REEXEC_ENV] == "1"
    assert captured["env"][rsd.CACHED_ENV] == "1"  # ...as a cache-created hop


def test_load_modules_does_not_probe_when_cached_interpreter_present():
    probes = []

    def fake_imports_solaar(python):
        probes.append(python)
        return True

    with mock.patch.dict(sys.modules, {"logitech_receiver": None}), \
            mock.patch.object(rsd, "cached_runner", lambda: "python:/cached/python"), \
            mock.patch.object(rsd, "candidate_interpreters", lambda: []), \
            mock.patch.object(rsd.os.path, "isfile", lambda p: True), \
            mock.patch.object(rsd.os, "execve",
                              lambda *a: (_ for _ in ()).throw(OSError("stop"))), \
            mock.patch.object(rsd, "imports_solaar", fake_imports_solaar):
        try:
            rsd.load_modules()
        except rsd.SolaarNotImportable:
            pass

    assert probes == []  # 30-240ms probe avoided entirely


def test_load_modules_stale_cached_interpreter_redisovers_clean():
    captured = {}

    def fake_execve(path, argv, env):
        captured["path"] = path
        captured["env"] = env
        raise OSError("stop after the exec attempt")

    with mock.patch.dict(sys.modules, {"logitech_receiver": None}), \
            mock.patch.object(rsd, "cached_runner",
                              lambda: f"python:{sys.executable}"), \
            mock.patch.object(rsd, "candidate_interpreters",
                              lambda: ["/other/python"]), \
            mock.patch.object(rsd, "imports_solaar", lambda python: True), \
            mock.patch.object(rsd.os.path, "isfile", lambda p: True), \
            mock.patch.object(rsd.os, "execve", fake_execve), \
            mock.patch.object(rsd, "clear_runner_cache") as clear_called, \
            mock.patch.dict(os.environ,
                            {rsd.CACHED_ENV: "1", rsd.REEXEC_ENV: "1"}):
        try:
            rsd.load_modules()
        except rsd.SolaarNotImportable:
            pass

    # the equal-but-failing interpreter cleared the stale token and popped the
    # re-exec flags, so the next interpreter is honestly discovered again
    clear_called.assert_called_once()
    assert captured["path"] == "/other/python"
    assert rsd.CACHED_ENV not in captured["env"]  # fresh discovery; not cached
    assert captured["env"][rsd.REEXEC_ENV] == "1"  # but still one re-exec deep


def test_load_modules_reexec_success_writes_the_cache_token():
    modules = types.SimpleNamespace(base=None, device=None, receiver=None)
    with mock.patch.dict(sys.modules, {"logitech_receiver": modules}), \
            mock.patch.dict(os.environ, {rsd.REEXEC_ENV: "1"}), \
            mock.patch.object(rsd, "write_runner_cache") as writer:
        rsd.load_modules()
    writer.assert_called_once_with(f"python:{sys.executable}")


def test_load_modules_native_success_does_not_write_the_cache():
    # the common case (this interpreter has Solaar): no re-exec, no token
    modules = types.SimpleNamespace(base=None, device=None, receiver=None)
    with mock.patch.dict(sys.modules, {"logitech_receiver": modules}), \
            mock.patch.dict(os.environ, {}, clear=True), \
            mock.patch.object(rsd, "write_runner_cache") as writer:
        rsd.load_modules()
    writer.assert_not_called()


def test_load_modules_success_inside_flatpak_does_not_write_the_cache():
    # the sandbox's own interpreter must never claim a host-side token
    modules = types.SimpleNamespace(base=None, device=None, receiver=None)
    with mock.patch.dict(sys.modules, {"logitech_receiver": modules}), \
            mock.patch.dict(os.environ, {rsd.REEXEC_ENV: "1", rsd.FLATPAK_ENV: "1"}), \
            mock.patch.object(rsd, "write_runner_cache") as writer:
        rsd.load_modules()
    writer.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# lib: Flatpak sandbox hand-off
# ══════════════════════════════════════════════════════════════════════════════

def test_flatpak_solaar_app_none_without_flatpak():
    with mock.patch.object(rsd.shutil, "which", lambda name: None):
        assert rsd.flatpak_solaar_app() is None


def test_flatpak_solaar_app_detects_installed_app():
    done = types.SimpleNamespace(returncode=0)
    with mock.patch.object(rsd.shutil, "which", lambda name: "/usr/bin/flatpak"), \
            mock.patch.object(rsd.subprocess, "run", lambda *a, **k: done):
        assert rsd.flatpak_solaar_app() == ("/usr/bin/flatpak", rsd.FLATPAK_SOLAAR_ID)


def test_flatpak_solaar_app_skips_inside_sandbox():
    # FLATPAK_ENV is set when running inside the sandbox: never recurse
    with mock.patch.dict(os.environ, {rsd.FLATPAK_ENV: "1"}), \
            mock.patch.object(rsd.shutil, "which", lambda name: "/usr/bin/flatpak"):
        assert rsd.flatpak_solaar_app() is None


def test_collect_via_flatpak_feeds_script_on_stdin_and_parses_json():
    devices = [{"name": "MX Master 3S", "serial": "s", "percentage": 72}]
    done = types.SimpleNamespace(returncode=0, stdout=json.dumps(devices).encode(),
                                 stderr=b"")
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["input"] = kwargs.get("input")
        calls["env"] = kwargs.get("env")
        return done

    with mock.patch.object(rsd.subprocess, "run", fake_run):
        result = rsd.collect_via_flatpak("/usr/bin/flatpak", rsd.FLATPAK_SOLAAR_ID)

    assert result == devices
    assert calls["cmd"] == ["/usr/bin/flatpak", "run", "--command=python3",
                            rsd.FLATPAK_SOLAAR_ID, "-"]
    assert b"logitech_receiver" in calls["input"]  # the helper's own source
    assert calls["env"][rsd.FLATPAK_ENV] == "1"


def test_collect_via_flatpak_returns_none_on_failure():
    done = types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"boom")
    with mock.patch.object(rsd.subprocess, "run", lambda *a, **k: done):
        assert rsd.collect_via_flatpak("/usr/bin/flatpak", rsd.FLATPAK_SOLAAR_ID) is None


def test_collect_via_flatpak_forwards_debug_into_the_sandbox():
    done = types.SimpleNamespace(returncode=0, stdout=b"[]", stderr=b"")
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return done

    with mock.patch.object(rsd, "DEBUG", True), \
            mock.patch.object(rsd.subprocess, "run", fake_run):
        rsd.collect_via_flatpak("/usr/bin/flatpak", rsd.FLATPAK_SOLAAR_ID)

    # sys.argv inside the sandbox becomes ['-', '--debug'], so diagnostics stay on
    assert calls["cmd"][-1] == "--debug"


def test_collect_flatpak_uses_the_cached_token():
    devices = [{"name": "MX Keys S", "serial": "s"}]
    with mock.patch.object(rsd, "cached_runner", lambda: "flatpak"), \
            mock.patch.object(rsd.shutil, "which", lambda name: "/usr/bin/flatpak"), \
            mock.patch.object(rsd, "collect_via_flatpak",
                              lambda flatpak, app_id: devices), \
            mock.patch.object(rsd, "write_runner_cache") as writer, \
            mock.patch.object(rsd, "clear_runner_cache") as clearer:
        assert rsd.collect_flatpak() == devices
    # a proven-good token is neither re-written nor cleared
    writer.assert_not_called()
    clearer.assert_not_called()


def test_collect_flatpak_stale_token_is_cleared():
    with mock.patch.object(rsd, "cached_runner", lambda: "flatpak"), \
            mock.patch.object(rsd.shutil, "which", lambda name: "/usr/bin/flatpak"), \
            mock.patch.object(rsd, "collect_via_flatpak", lambda flatpak, app_id: None), \
            mock.patch.object(rsd, "write_runner_cache") as writer, \
            mock.patch.object(rsd, "clear_runner_cache") as clearer:
        assert rsd.collect_flatpak() is None
    clearer.assert_called_once()
    writer.assert_not_called()


def test_collect_flatpak_cached_token_without_flatpak_binary_clears():
    with mock.patch.object(rsd, "cached_runner", lambda: "flatpak"), \
            mock.patch.object(rsd.shutil, "which", lambda name: None), \
            mock.patch.object(rsd, "clear_runner_cache") as clearer:
        assert rsd.collect_flatpak() is None
    clearer.assert_called_once()


def test_collect_flatpak_detects_and_caches_on_success():
    devices = [{"name": "M305", "serial": "s"}]
    with mock.patch.object(rsd, "cached_runner", lambda: None), \
            mock.patch.object(rsd, "flatpak_solaar_app",
                              lambda: ("/usr/bin/flatpak", rsd.FLATPAK_SOLAAR_ID)), \
            mock.patch.object(rsd, "collect_via_flatpak",
                              lambda flatpak, app_id: devices), \
            mock.patch.object(rsd, "write_runner_cache") as writer:
        assert rsd.collect_flatpak() == devices
    writer.assert_called_once_with("flatpak")


def test_collect_flatpak_detection_failure_returns_none_without_cache():
    with mock.patch.object(rsd, "cached_runner", lambda: None), \
            mock.patch.object(rsd, "flatpak_solaar_app", lambda: None), \
            mock.patch.object(rsd, "write_runner_cache") as writer:
        assert rsd.collect_flatpak() is None
    writer.assert_not_called()


def test_collect_flatpak_inside_sandbox_touches_nothing():
    # The inner run must never hand off or manage the host-side cache, even if
    # a future manifest exposes it: FLATPAK_ENV short-circuits everything.
    with mock.patch.dict(os.environ, {rsd.FLATPAK_ENV: "1"}), \
            mock.patch.object(rsd, "cached_runner",
                              lambda: (_ for _ in ()).throw(AssertionError("cache read"))), \
            mock.patch.object(rsd, "write_runner_cache") as writer, \
            mock.patch.object(rsd, "clear_runner_cache") as clearer:
        assert rsd.collect_flatpak() is None
    writer.assert_not_called()
    clearer.assert_not_called()


def test_main_cached_flatpak_skips_host_discovery():
    devices = [{"name": "M305", "serial": "s"}]
    buffer = io.StringIO()
    with mock.patch.object(rsd, "cached_runner", lambda: "flatpak"), \
            mock.patch.object(rsd, "collect_flatpak", lambda: devices), \
            mock.patch.object(rsd, "load_modules",
                              lambda: (_ for _ in ()).throw(AssertionError("host probed"))):
        with redirect_stdout(buffer):
            rsd.main()
    assert json.loads(buffer.getvalue().strip()) == devices


def test_main_stale_flatpak_cache_falls_back_to_host_path():
    # a stale flatpak token returns None from collect_flatpak; main falls back
    # to the normal host path (which reports the real error object)
    def raise_unimportable():
        raise rsd.SolaarNotImportable("not installed")

    buffer = io.StringIO()
    with mock.patch.object(rsd, "cached_runner", lambda: "flatpak"), \
            mock.patch.object(rsd, "collect_flatpak", lambda: None), \
            mock.patch.object(rsd, "load_modules", raise_unimportable):
        with redirect_stdout(buffer):
            rsd.main()
    parsed = json.loads(buffer.getvalue().strip())
    assert parsed["error"] == "solaar-missing"


# ══════════════════════════════════════════════════════════════════════════════
# udev + simulate
# ══════════════════════════════════════════════════════════════════════════════

def test_udev_rule_covers_logitech_transports():
    rule = rsd.udev_rule()
    assert 'ATTRS{idVendor}=="046d"' in rule                    # Logitech
    assert 'ATTRS{idVendor}=="17ef"' in rule and "6042" in rule  # Lenovo receiver
    assert 'KERNELS=="0005:046D:*"' in rule                     # Bluetooth Logitech
    assert 'TAG+="uaccess"' in rule


def test_unblock_command_writes_the_rule_file():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(rsd, "UDEV_RULES_DIR", tmp):
            path = rsd.udev_rule_path()
            command = rsd.udev_unblock_command()
            assert path.startswith(tmp)
            assert f"tee {path}" in command
            assert "udevadm control --reload-rules" in command


def test_simulate_reports_blocked_until_the_rule_exists():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(rsd, "UDEV_RULES_DIR", tmp):
            # no rule file yet: the fake devices look blocked
            entries = rsd.simulate()
            assert all(e.get("blocked") is True for e in entries)
            assert all("unblock_command" in e for e in entries)
            # once the rule exists the same devices report batteries
            os.makedirs(os.path.join(tmp, "70-batterywatch-solaar.rules"))
            entries = rsd.simulate()
            assert all(e.get("blocked") is not True for e in entries)
            assert {e["percentage"] for e in entries} == {72, 38, 90}
            assert {e["deviceType"] for e in entries} == {"mouse", "audio-headset", "keyboard"}
            assert any(e["charging"] is True for e in entries)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def run_helper(*args, extra_env=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, HELPER, *args], capture_output=True, text=True,
                          cwd=os.path.dirname(HELPER), timeout=30, env=env)


def test_helper_simulate_json_shape():
    r = run_helper("--simulate")
    assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr!r}"
    parsed = json.loads(r.stdout.strip())
    assert isinstance(parsed, list) and len(parsed) >= 3
    assert all("name" in e and "serial" in e for e in parsed)
    assert all(("percentage" in e) or e.get("blocked") is True for e in parsed)
    # simulated devices are added to (not substituted for) the real ones
    assert sum(e["serial"].startswith("sim-") for e in parsed) == 3


def test_debug_flag_keeps_stdout_valid_json():
    r = run_helper("--debug", "--simulate")
    assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr!r}"
    # stderr belongs to our own debugging: every line must carry the marker
    for line in r.stderr.splitlines():
        assert line.startswith("[batterywatch]") or "Wayland" in line, f"stderr={r.stderr!r}"
    assert isinstance(json.loads(r.stdout.strip()), list), f"stdout={r.stdout.strip()!r}"


def test_main_unavailable_path_prints_error_object():
    # Break the import (no machine has Solaar inside this sandbox test) and
    # make one error object show up instead of a traceback on stdout.
    def raise_unimportable():
        raise rsd.SolaarNotImportable("not installed")

    buffer = io.StringIO()
    with mock.patch.object(rsd, "load_modules", raise_unimportable), \
            mock.patch.object(rsd, "flatpak_solaar_app", lambda: None), \
            mock.patch.object(rsd, "cached_runner", lambda: None), \
            mock.patch.object(rsd, "collect_flatpak", lambda: None):
        with redirect_stdout(buffer):
            rsd.main()
    parsed = json.loads(buffer.getvalue().strip())
    assert parsed["error"] == "solaar-missing"
    assert "not installed" in parsed["hint"]


# ══════════════════════════════════════════════════════════════════════════════
# Zero-dependency runner: collects the test_*() functions above and runs them
# in definition order. pytest discovers the same functions if it's installed.
# ══════════════════════════════════════════════════════════════════════════════
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
