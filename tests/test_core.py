import hashlib
import io
import json
import struct
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from qmk_updater.firmware import Firmware, FirmwareError, Segment, FLASH_BASE, load_firmware, parse_hex
from qmk_updater.package import (Package, Settings, create_executable, decode_package,
                                 encode_package, read_overlay)
from qmk_updater.wb32 import Wb32, UpgradeError
from qmk_updater.workflow import upgrade

ROOT = Path(__file__).resolve().parent.parent


def image(extra=b"\x12\x34", offset=0):
    return Firmware("test.bin", [Segment(FLASH_BASE + offset,
                    struct.pack("<II", 0x20000400, FLASH_BASE + offset + 9) + extra)], "0" * 64)


def record(address, kind, data=b""):
    data = bytes([len(data)]) + struct.pack(">H", address) + bytes([kind]) + data
    return ":" + (data + bytes([-sum(data) & 255])).hex().upper()


class FakeTransport:
    packet_size = 64

    def __init__(self):
        self.memory = bytearray(b"\x5a" * (256 * 1024))
        self.commands = []
        self.response = b""
        self.closed = False
        self.reset_called = False
        self.protected = False
        self.corrupt = False
        self.short_write = False
        self.bad_status = 0
        self.flash_size = 256 * 1024
        self.chip_id = 0x3a50e980

    def write(self, data):
        self.commands.append(data)
        if not data:
            return 0
        if self.short_write:
            return len(data) - 1
        cmd = data[0]
        self.response = bytes([cmd, self.bad_status])
        if self.bad_status:
            return len(data)
        if cmd == 1:
            self.response += b"\x0d" + struct.pack("<BIII", 4, self.chip_id, self.flash_size, 36 * 1024)
        elif cmd in (0x72, 0x5e, 0x6a):
            if self.protected:
                self.response = bytes([cmd, 0x1a])
                return len(data)
            address = struct.unpack_from("<I", data, 4)[0] - FLASH_BASE
            if cmd == 0x72:
                n = struct.unpack_from("<H", data, 8)[0]
                self.response += self.memory[address:address + n]
                if self.corrupt and any(c and c[0] == 0x6a for c in self.commands):
                    self.response = self.response[:-1] + bytes([self.response[-1] ^ 1])
            elif cmd == 0x5e:
                self.memory[address:address + 256] = b"\xff" * 256
            else:
                n = struct.unpack_from("<I", data, 8)[0]
                self.memory[address:address + n] = data[12:12 + n]
        elif cmd == 0x83:
            self.reset_called = True
        return len(data)

    def read(self, count):
        return self.response

    def close(self):
        self.closed = True


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, value):
        self.now += value


class FakeHardware:
    def __init__(self, apps=1, boots=0):
        self.apps = apps
        self.boots = boots
        self.jumps = 0
        self.transport = FakeTransport()
        self.jump_works = True
        self.returns = True

    def app_devices(self, settings, target=False):
        if self.transport.reset_called:
            return [{"path": b"app"}] if self.returns and target else []
        return [{"path": b"app"}] * self.apps

    def boot_devices(self, settings):
        return [] if self.transport.reset_called else ["boot"] * self.boots

    def jump(self, device, settings):
        self.jumps += 1
        if self.jump_works:
            self.apps, self.boots = 0, 1

    def open_boot(self, device):
        return self.transport


class FirmwareTests(unittest.TestCase):
    def test_user_firmware_identity(self):
        firmware = load_firmware(ROOT / "mk20b_via_v9.hex")
        self.assertEqual(firmware.base, 0x08000000)
        self.assertEqual(firmware.size, 74068)
        usb, = firmware.usb_candidates()
        self.assertEqual((usb.vid, usb.pid, usb.version), (0x342d, 0xe594, 9))
        self.assertEqual(usb.usb_version, 0x0200)
        hid, = firmware.hid_candidates()
        self.assertEqual((hid.usage_page, hid.usage, hid.report_size, hid.report_id), (0xff60, 0x61, 32, 0))
        self.assertIn("SAMURAI S-751 Keyboard", firmware.strings())

    def test_hex_preserves_gaps_and_extended_address(self):
        text = "\n".join([record(0, 4, b"\x08\x00"), record(0, 0, b"abcd"),
                          record(32, 0, b"efgh"), record(0, 1)])
        segments = parse_hex(text.encode())
        self.assertEqual(segments, [Segment(FLASH_BASE, b"abcd"), Segment(FLASH_BASE + 32, b"efgh")])

    def test_bad_checksum(self):
        with self.assertRaises(FirmwareError):
            parse_hex(b":02000004080000\n:00000001FF")

    def test_hex_requires_eof(self):
        with self.assertRaises(FirmwareError):
            parse_hex((record(0, 4, b"\x08\x00") + "\n" + record(0, 0, b"ab")).encode())

    def test_hex_overlap_and_outside_flash(self):
        for records in ([record(0, 4, b"\x08\x00"), record(0, 0, b"a"), record(0, 0, b"a")],
                        [record(0, 4, b"\x20\x00"), record(0, 0, b"ab")]):
            with self.assertRaises(FirmwareError):
                parse_hex(("\n".join(records + [record(0, 1)])).encode())

    def test_hex_rejects_trailing_records(self):
        with self.assertRaises(FirmwareError):
            parse_hex((record(0, 1) + "\n" + record(0, 0, b"x")).encode())

    def test_bin_and_hex_equivalent(self):
        f = load_firmware(ROOT / "mk20b_via_v9.hex")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.BIN"
            path.write_bytes(f.segments[0].data)
            self.assertEqual(load_firmware(path).segments, f.segments)

    def test_vector_check(self):
        for data in (b"\0" * 32, struct.pack("<II", 0x20000400, FLASH_BASE + 8) + b"xx"):
            with self.assertRaises(FirmwareError):
                Firmware("bad", [Segment(FLASH_BASE, data)], "0" * 64).validate()


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.package = Package(Settings(), image())

    def test_roundtrip(self):
        result = decode_package(encode_package(self.package))
        self.assertEqual(result, self.package)

    def test_modified_firmware_rejected(self):
        original = zipfile.ZipFile(io.BytesIO(encode_package(self.package)))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as out:
            for name in original.namelist():
                out.writestr(name, b"modified" if name.endswith(".bin") else original.read(name))
        with self.assertRaises(FirmwareError):
            decode_package(stream.getvalue())

    def test_overlay_and_repack(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "template.exe"
            out = Path(temp) / "out.exe"
            out2 = Path(temp) / "out2.exe"
            base.write_bytes(b"MZ" + b"fake-executable" * 10)
            data = encode_package(self.package)
            create_executable(base, out, data)
            self.assertEqual(read_overlay(out), data)
            create_executable(out, out2, data)
            self.assertEqual(out.read_bytes(), out2.read_bytes())
            corrupted = bytearray(out.read_bytes())
            corrupted[-60] ^= 1
            out.write_bytes(corrupted)
            with self.assertRaises(FirmwareError):
                read_overlay(out)

    def test_self_overwrite_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "base"
            base.write_bytes(b"MZ")
            with self.assertRaises(FirmwareError):
                create_executable(base, base, encode_package(self.package))

    def test_authenticode_alignment_and_repack(self):
        with tempfile.TemporaryDirectory() as temp:
            template, output, repacked = [Path(temp) / n for n in ("base.exe", "signed.exe", "repacked.exe")]
            pe = bytearray(512)
            pe[:2] = b"MZ"
            struct.pack_into("<I", pe, 60, 0x80)
            pe[0x80:0x84] = b"PE\0\0"
            struct.pack_into("<H", pe, 0x80 + 24, 0x20b)
            struct.pack_into("<I", pe, 0x80 + 24 + 108, 16)
            template.write_bytes(pe)
            data = encode_package(self.package)
            create_executable(template, output, data)
            signed = bytearray(output.read_bytes())
            signed.extend(bytes((-len(signed)) % 8))
            cert_offset = len(signed)
            # A structural fixture only; no real signing key or trust assertion.
            signed.extend(struct.pack("<IHH", 16, 0x200, 2) + bytes(8))
            struct.pack_into("<II", signed, 0x80 + 24 + 112 + 32, cert_offset, 16)
            output.write_bytes(signed)
            self.assertEqual(read_overlay(output), data)
            create_executable(output, repacked, data)
            self.assertEqual(read_overlay(repacked), data)
            self.assertEqual(repacked.read_bytes()[0x80 + 24 + 112 + 32:0x80 + 24 + 112 + 40], bytes(8))

    def test_bad_settings(self):
        for settings in (replace(Settings(), app_vid=-1), replace(Settings(), report_size=0),
                         replace(Settings(), accent="red"), replace(Settings(), product=3),
                         replace(Settings(), app_pid=0xdfa0), replace(Settings(), auto_start=1),
                         replace(Settings(), burn_mode="unsupported"), replace(Settings(), background="white")):
            with self.assertRaises(FirmwareError):
                settings.validate()


class ProtocolTests(unittest.TestCase):
    def test_flash_preserves_rest_of_page_and_sparse_gap(self):
        transport = FakeTransport()
        f = image()
        f.segments.append(Segment(FLASH_BASE + 400, b"sparse"))
        Wb32(transport).flash(f)
        self.assertEqual(transport.memory[:10], f.segments[0].data)
        self.assertEqual(transport.memory[10:400], b"\x5a" * 390)
        self.assertEqual(transport.memory[400:406], b"sparse")
        self.assertFalse(transport.reset_called)
        self.assertEqual(len([c for c in transport.commands if c and c[0] == 0x5e]), 2)

    def test_exact_page_does_not_erase_next_page(self):
        transport = FakeTransport()
        Wb32(transport).flash(image(b"\x11" * 248))
        erases = [struct.unpack_from("<I", c, 4)[0] for c in transport.commands if c and c[0] == 0x5e]
        self.assertEqual(erases, [FLASH_BASE])

    def test_unchanged_page_skips_erase(self):
        transport = FakeTransport()
        firmware = image()
        transport.memory[:firmware.size] = firmware.segments[0].data
        Wb32(transport).flash(firmware)
        self.assertFalse(any(c and c[0] == 0x5e for c in transport.commands))

    def test_read_protection_never_erases_or_unlocks(self):
        transport = FakeTransport()
        transport.protected = True
        with self.assertRaises(UpgradeError):
            Wb32(transport).flash(image())
        self.assertFalse(any(c and c[0] in (0x5e, 0x6a) for c in transport.commands))

    def test_failed_verification_never_resets(self):
        transport = FakeTransport()
        transport.corrupt = True
        with self.assertRaises(UpgradeError):
            Wb32(transport).flash(image())
        self.assertFalse(transport.reset_called)

    def test_wrong_chip_or_capacity_never_erases(self):
        for chip, size in ((0, 256 * 1024), (0x3a50e980, 128 * 1024)):
            transport = FakeTransport()
            transport.chip_id, transport.flash_size = chip, size
            with self.assertRaises(UpgradeError):
                Wb32(transport).flash(image())
            self.assertFalse(any(c and c[0] == 0x5e for c in transport.commands))

    def test_short_write_and_response(self):
        transport = FakeTransport()
        transport.short_write = True
        with self.assertRaises(UpgradeError):
            Wb32(transport).info()
        transport.short_write = False
        transport.read = lambda n: b"\x01"
        with self.assertRaises(UpgradeError):
            Wb32(transport).info()

    def test_zlp(self):
        transport = FakeTransport()
        flasher = Wb32(transport)
        flasher.exchange(b"\x01\x00" + b"\0" * 62, 16)
        self.assertEqual(transport.commands[-1], b"")


class WorkflowTests(unittest.TestCase):
    def run_upgrade(self, hardware, settings=None):
        clock = FakeClock()
        return upgrade(Package(settings or Settings(), image()), hardware,
                       timeout=1, clock=clock.clock, sleep=clock.sleep)

    def test_happy_path(self):
        hardware = FakeHardware()
        result = self.run_upgrade(hardware)
        self.assertTrue(result.reconnected)
        self.assertEqual(hardware.jumps, 1)
        self.assertTrue(hardware.transport.reset_called)
        self.assertTrue(hardware.transport.closed)

    def test_no_keyboard_and_multiple_devices_never_jump(self):
        for apps, boots in ((0, 0), (2, 0), (1, 1), (0, 2)):
            hardware = FakeHardware(apps, boots)
            with self.assertRaises(UpgradeError):
                self.run_upgrade(hardware)
            self.assertEqual(hardware.jumps, 0)
            self.assertFalse(hardware.transport.commands)

    def test_jump_timeout_never_writes_flash(self):
        hardware = FakeHardware()
        hardware.jump_works = False
        with self.assertRaises(UpgradeError):
            self.run_upgrade(hardware)
        self.assertFalse(hardware.transport.commands)

    def test_direct_boot_is_supported_without_a_separate_package_option(self):
        hardware = FakeHardware(0, 1)
        result = self.run_upgrade(hardware, replace(Settings(), allow_boot_recovery=False))
        self.assertTrue(result.reconnected)
        self.assertEqual(hardware.jumps, 0)

    def test_reconnect_timeout_is_not_reported_as_success(self):
        hardware = FakeHardware()
        hardware.returns = False
        self.assertFalse(self.run_upgrade(hardware).reconnected)

    def test_failure_releases_transport(self):
        hardware = FakeHardware()
        hardware.transport.corrupt = True
        with self.assertRaises(UpgradeError):
            self.run_upgrade(hardware)
        self.assertTrue(hardware.transport.closed)
        self.assertFalse(hardware.transport.reset_called)


if __name__ == "__main__":
    unittest.main()
