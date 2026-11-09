"""Packaging stays responsive without weakening the template integrity checks."""
import io
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from qmk_updater.firmware import FLASH_BASE, Firmware, FirmwareError, Segment
from qmk_updater.package import Package, Settings, encode_package, read_overlay
from qmk_updater.runtimes import create_runtime_archive, system_package, validate_runtime


class WindowsPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        firmware = Firmware("fixture.bin", [Segment(FLASH_BASE,
            struct.pack("<II", 0x20000400, FLASH_BASE + 9) + b"\x12\x34")], "0" * 64)
        self.data = encode_package(Package(Settings(), firmware))
        binary = bytearray(256)
        binary[:2] = b"MZ"
        struct.pack_into("<I", binary, 60, 0x80)
        binary[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<H", binary, 0x84, 0x8664)
        self.native = self.root / "template.exe"
        self.native.write_bytes(binary)

    def runtime(self):
        runtime = self.root / "windows-x64.qmk-runtime.zip"
        create_runtime_archive(self.native, runtime, "windows-x64")
        return runtime

    def tampered_runtime(self):
        runtime = self.runtime()
        stream = io.BytesIO()
        with zipfile.ZipFile(runtime) as source, zipfile.ZipFile(stream, "w") as changed:
            for info in source.infolist():
                content = source.read(info)
                if info.filename.startswith("runtime/"):
                    # Preserve byte count and regenerate a valid ZIP CRC. Only
                    # the SHA-256 from the unchanged manifest can detect this.
                    content = content[:-1] + bytes([content[-1] ^ 1])
                changed.writestr(info, content)
        runtime.write_bytes(stream.getvalue())
        return runtime

    def test_native_executable_is_packaged_without_zip_recompression(self):
        output = self.root / "customer.exe"
        with patch("qmk_updater.runtimes.create_runtime_archive",
                   side_effect=AssertionError("Native executable must not be recompressed")):
            system_package(self.native, output, self.data, "windows-x64")
        self.assertEqual(read_overlay(output), self.data)
        self.assertTrue(output.read_bytes().startswith(self.native.read_bytes()))

    def test_archive_executable_is_read_once_for_hashing_and_extraction(self):
        runtime = self.runtime()
        output = self.root / "customer.exe"
        reads = []
        original_open = zipfile.ZipFile.open

        def counted_open(archive, name, mode="r", *args, **kwargs):
            filename = getattr(name, "filename", name)
            if mode == "r" and filename.startswith("runtime/"):
                reads.append(filename)
            return original_open(archive, name, mode, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "open", counted_open):
            system_package(runtime, output, self.data, "windows-x64")
        self.assertEqual(reads, ["runtime/QMK-Firmware-Studio.exe"])
        self.assertEqual(read_overlay(output), self.data)

    def test_native_and_archive_progress_runs_monotonically_from_zero_to_complete(self):
        for template in (self.native, self.runtime()):
            with self.subTest(template=template.name):
                updates = []
                system_package(template, self.root / "customer.exe", self.data, "windows-x64",
                               progress=lambda value, text: updates.append((value, text)))
                values = [value for value, text in updates]
                self.assertEqual(values[0], 0)
                self.assertEqual(values[-1], 100)
                self.assertEqual(values, sorted(values))
                self.assertTrue(all(0 <= value <= 100 for value in values))
                self.assertTrue(all(isinstance(text, str) and text for value, text in updates))

    def test_sha256_failure_preserves_existing_output(self):
        runtime = self.tampered_runtime()
        output = self.root / "customer.exe"
        output.write_bytes(b"previous-valid-delivery")
        with patch("qmk_updater.runtimes.create_executable") as assemble:
            with self.assertRaisesRegex(FirmwareError, "完整性校验失败"):
                system_package(runtime, output, self.data, "windows-x64")
        assemble.assert_not_called()
        self.assertEqual(output.read_bytes(), b"previous-valid-delivery")

    def test_sha256_failure_extracts_only_to_disposable_work_file(self):
        runtime = self.tampered_runtime()
        output = self.root / "customer.exe"
        extracted = []

        def inspect_destination(*args, **kwargs):
            extracted.append(Path(kwargs["executable_destination"]))
            self.assertNotEqual(extracted[-1], output)
            return validate_runtime(*args, **kwargs)

        with patch("qmk_updater.runtimes.validate_runtime", side_effect=inspect_destination):
            with self.assertRaises(FirmwareError):
                system_package(runtime, output, self.data, "windows-x64")
        self.assertEqual(len(extracted), 1)
        self.assertFalse(extracted[0].exists())
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
