import hashlib
import io
import json
import stat
import struct
import tarfile
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from qmk_updater.firmware import FirmwareError
from qmk_updater.package import Package, Settings, encode_package, decode_package, read_overlay, embedded_package
from qmk_updater.runtimes import create_runtime_archive, validate_runtime, install_runtime, system_package, PAYLOAD_NAME, _zip_info
from test_core import image


def binary_header(target):
    if target.startswith("macos"):
        return b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x100000c if target == "macos-arm64" else 0x1000007) + bytes(120)
    if target.startswith("linux"):
        data = bytearray(128)
        data[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", data, 18, 62)
        return bytes(data)
    data = bytearray(256)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x84, 0x8664)
    return bytes(data)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = encode_package(Package(replace(Settings(), auto_start=False, background="#11151C"), image()))

    def tearDown(self):
        self.temp.cleanup()

    def runtime(self, target):
        if target.startswith("macos"):
            native = self.root / (target + ".app")
            executable = native / "Contents" / "MacOS" / "QMK-Firmware-Studio"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(binary_header(target))
            seal = native / "Contents" / "_CodeSignature" / "CodeResources"
            seal.parent.mkdir()
            seal.write_bytes(b"unchanged-signature-resource-fixture")
        else:
            native = self.root / (target + ".bin")
            native.write_bytes(binary_header(target))
        runtime = self.root / (target + ".qmk-runtime.zip")
        create_runtime_archive(native, runtime, target)
        return runtime

    def test_mac_package_assembled_without_codesign_or_running_target_binary(self):
        for target in ("macos-arm64", "macos-x64"):
            runtime = self.runtime(target)
            output = self.root / (target + "-customer.zip")
            with patch("subprocess.run", side_effect=AssertionError("No target commands allowed")):
                system_package(runtime, output, self.data, target)
            meta = validate_runtime(runtime)
            prefix = output.stem + "/" + output.stem + ".app"
            with zipfile.ZipFile(runtime) as source, zipfile.ZipFile(output) as result:
                for item in meta["entries"]:
                    renamed = prefix + item["name"][len(meta["root"]):]
                    self.assertEqual(result.read(renamed), source.read("runtime/" + item["name"]))
                    self.assertEqual(result.getinfo(renamed).external_attr >> 16, item["mode"])
                payload = result.read(output.stem + "/" + PAYLOAD_NAME)
                settings = decode_package(payload).settings
                self.assertFalse(settings.auto_start)
                self.assertEqual(settings.background, "#11151C")

    def test_framework_symlinks_survive_packaging_on_windows(self):
        runtime = self.runtime("macos-arm64")
        stream = io.BytesIO()
        with zipfile.ZipFile(runtime) as source, zipfile.ZipFile(stream, "w") as out:
            meta = json.loads(source.read("runtime.json"))
            for info in source.infolist():
                if info.filename != "runtime.json":
                    out.writestr(info, source.read(info))
            name = meta["root"] + "/Contents/Frameworks/F.framework/Versions/Current"
            content = b"A"
            mode = stat.S_IFLNK | 0o777
            out.writestr(_zip_info("runtime/" + name, mode), content)
            meta["entries"].append({"name": name, "size": 1, "mode": mode, "sha256": hashlib.sha256(content).hexdigest()})
            out.writestr("runtime.json", json.dumps(meta))
        runtime.write_bytes(stream.getvalue())
        output = self.root / "keyboard.zip"
        system_package(runtime, output, self.data, "macos-arm64")
        with zipfile.ZipFile(output) as archive:
            link = archive.getinfo("keyboard/keyboard.app/Contents/Frameworks/F.framework/Versions/Current")
            self.assertTrue(stat.S_ISLNK(link.external_attr >> 16))
            self.assertEqual(archive.read(link), b"A")

    def test_linux_tar_keeps_executable_bit_and_embedded_settings(self):
        output = self.root / "keyboard.tar.gz"
        system_package(self.runtime("linux-x64"), output, self.data, "linux-x64")
        with tarfile.open(output) as archive:
            member = archive.getmembers()[0]
            self.assertEqual(member.mode, 0o755)
            executable = self.root / "linux-updater"
            executable.write_bytes(archive.extractfile(member).read())
        self.assertEqual(read_overlay(executable), self.data)

    def test_windows_template_makes_single_exe(self):
        output = self.root / "keyboard.exe"
        system_package(self.runtime("windows-x64"), output, self.data, "windows-x64")
        self.assertTrue(output.read_bytes().startswith(b"MZ"))
        self.assertEqual(read_overlay(output), self.data)

    def test_wrong_target_and_wrong_binary_are_rejected(self):
        runtime = self.runtime("macos-arm64")
        with self.assertRaises(FirmwareError):
            system_package(runtime, self.root / "bad.exe", self.data, "windows-x64")
        native = self.root / "wrong"
        native.write_bytes(binary_header("windows-x64"))
        with self.assertRaises(FirmwareError):
            create_runtime_archive(native, self.root / "bad.qmk-runtime.zip", "linux-x64")

    def test_mac_runtime_reads_the_hidden_sibling_firmware_package(self):
        executable = self.root / "Keyboard.app" / "Contents" / "MacOS" / "QMK-Firmware-Studio"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(binary_header("macos-arm64"))
        (self.root / PAYLOAD_NAME).write_bytes(self.data)
        with patch("qmk_updater.package.sys.frozen", True, create=True), \
             patch("qmk_updater.package.sys.executable", str(executable)), \
             patch("qmk_updater.package.sys.platform", "darwin"):
            package = embedded_package()
        self.assertEqual(package.settings.background, "#11151C")
        self.assertFalse(package.settings.auto_start)

    def test_import_all_platforms_bundle(self):
        paths = [self.runtime("macos-arm64"), self.runtime("linux-x64")]
        bundle = self.root / "all-templates.zip"
        with zipfile.ZipFile(bundle, "w") as archive:
            for path in paths:
                archive.write(path, "templates/" + path.name)
        destination = self.root / "templates"
        self.assertEqual(set(install_runtime(bundle, destination)), {"macos-arm64", "linux-x64"})
        self.assertEqual(validate_runtime(destination / "macos-arm64.qmk-runtime.zip")["target"], "macos-arm64")

    def test_template_tampering_and_escaping_paths_are_rejected(self):
        runtime = self.runtime("linux-x64")
        for escaping in (False, True):
            stream = io.BytesIO()
            with zipfile.ZipFile(runtime) as source, zipfile.ZipFile(stream, "w") as out:
                for info in source.infolist():
                    data = source.read(info)
                    if info.filename.startswith("runtime/") and not escaping:
                        data = b"changed"
                    if info.filename == "runtime.json" and escaping:
                        meta = json.loads(data)
                        meta["entries"][0]["name"] = "../escape"
                        data = json.dumps(meta).encode()
                    out.writestr(info, data)
            with self.assertRaises(FirmwareError):
                validate_runtime(io.BytesIO(stream.getvalue()))
