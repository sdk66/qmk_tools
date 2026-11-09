"""Validated portable packages and native executable overlays."""
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .firmware import Firmware, Segment, FirmwareError, FLASH_BASE, MAX_FLASH

MAGIC = b"QMK-WB32-PKG-V1!\0"
FOOTER_SIZE = 8 + 32 + len(MAGIC)
MAX_PACKAGE = 2 * 1024 * 1024


@dataclass
class Settings:
    product: str = "QMK Keyboard"
    version: str = "1.0.0"
    app_vid: int = 0x342d
    app_pid: int = 0xe594
    usage_page: int = 0xff60
    usage_id: int = 0x61
    report_size: int = 32
    report_id: int = 0
    boot_vid: int = 0x342d
    boot_pid: int = 0xdfa0
    target_vid: int = 0x342d
    target_pid: int = 0xe594
    target_usage_page: int = 0xff60
    target_usage_id: int = 0x61
    accent: str = "#83ADF2"
    auto_start: bool = True
    # Kept in the manifest for compatibility with existing packages. Both APP
    # and a manually entered Boot are always accepted by the runtime.
    allow_boot_recovery: bool = True
    burn_mode: str = "single"
    background: str = "#FFFFFF"

    def validate(self):
        if (type(self.product) is not str or type(self.version) is not str
                or not self.product.strip() or len(self.product) > 100 or not self.version.strip() or len(self.version) > 40):
            raise FirmwareError("请填写设备名称和固件版本（名称不超过 100 字）。")
        for key in ("app_vid", "app_pid", "usage_page", "usage_id", "boot_vid", "boot_pid",
                    "target_vid", "target_pid", "target_usage_page", "target_usage_id"):
            value = getattr(self, key)
            if type(value) is not int or not 0 <= value <= 0xffff:
                raise FirmwareError("%s 必须为 0000–FFFF 的十六进制值。" % key)
        if not self.app_vid or not self.boot_vid or self.app_vid == 0xffff or self.boot_vid == 0xffff:
            raise FirmwareError("VID 无效。")
        if type(self.report_size) is not int or not 1 <= self.report_size <= 1024:
            raise FirmwareError("Raw HID 报告长度必须为 1–1024 字节。")
        if type(self.report_id) is not int or not 0 <= self.report_id <= 255:
            raise FirmwareError("Report ID 必须为 00–FF。")
        if (type(self.accent) is not str or len(self.accent) != 7 or self.accent[0] != "#"
                or any(c not in "0123456789abcdefABCDEF" for c in self.accent[1:])):
            raise FirmwareError("主题颜色无效。")
        if type(self.auto_start) is not bool or type(self.allow_boot_recovery) is not bool:
            raise FirmwareError("升级选项无效。")
        if self.burn_mode not in ("single", "continuous"):
            raise FirmwareError("烧录模式必须为单次烧录或连续烧录。")
        if (type(self.background) is not str or len(self.background) != 7 or self.background[0] != "#"
                or any(c not in "0123456789abcdefABCDEF" for c in self.background[1:])):
            raise FirmwareError("升级页背景颜色无效。")
        if (self.app_vid, self.app_pid) == (self.boot_vid, self.boot_pid):
            raise FirmwareError("APP 和 Boot 的 VID/PID 不能相同。")


@dataclass
class Package:
    settings: Settings
    firmware: Firmware


def encode_package(package):
    package.settings.validate()
    package.firmware.validate()
    segments = []
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, segment in enumerate(package.firmware.segments):
            name = "firmware/%d.bin" % index
            archive.writestr(name, segment.data)
            segments.append({"file": name, "address": segment.address,
                             "size": len(segment.data), "sha256": hashlib.sha256(segment.data).hexdigest()})
        manifest = {"format": 1, "chip": "WB32FQ95", "settings": asdict(package.settings),
                    "firmware": {"name": package.firmware.name,
                                 "source_sha256": package.firmware.source_sha256, "segments": segments}}
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return stream.getvalue()


def decode_package(data):
    if len(data) > MAX_PACKAGE:
        raise FirmwareError("升级包过大。")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if (len(names) != len(set(names)) or len(infos) > 1025
                    or sum(i.file_size for i in infos) > MAX_PACKAGE):
                raise FirmwareError("升级包内容无效。")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest["format"] != 1 or manifest["chip"] != "WB32FQ95":
                raise FirmwareError("升级包版本或芯片不受支持。")
            settings = Settings(**manifest["settings"])
            settings.validate()
            segments = []
            expected_names = {"manifest.json"}
            for index, item in enumerate(manifest["firmware"]["segments"]):
                if item["file"] != "firmware/%d.bin" % index or type(item["address"]) is not int:
                    raise FirmwareError("固件段定义无效。")
                content = archive.read(item["file"])
                if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
                    raise FirmwareError("固件 SHA-256 校验失败，升级包已损坏。")
                segments.append(Segment(item["address"], content))
                expected_names.add(item["file"])
            if set(names) != expected_names:
                raise FirmwareError("升级包含未声明的文件。")
            firmware = Firmware(manifest["firmware"]["name"], segments, manifest["firmware"]["source_sha256"])
            firmware.validate()
            return Package(settings, firmware)
    except FirmwareError:
        raise
    except (ValueError, TypeError, KeyError, OSError, zipfile.BadZipFile, RuntimeError) as e:
        raise FirmwareError("升级包无法读取：%s" % e)


def _pe_certificate(stream):
    """Return the PE security-directory field and certificate offset, if any."""
    stream.seek(0, 2)
    size = stream.tell()
    if size < 64:
        return None
    stream.seek(0)
    header = stream.read(64)
    if header[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", header, 60)[0]
    if pe < 64 or pe + 24 + 152 > size:
        return None
    stream.seek(pe)
    header = stream.read(24 + 152)
    if header[:4] != b"PE\0\0":
        return None
    magic = struct.unpack_from("<H", header, 24)[0]
    if magic not in (0x10b, 0x20b):
        return None
    directories = 24 + (96 if magic == 0x10b else 112)
    count = struct.unpack_from("<I", header, directories - 4)[0]
    if count < 5:
        return None
    field = pe + directories + 4 * 8
    offset, length = struct.unpack_from("<II", header, directories + 4 * 8)
    if offset % 8 or length < 8 or offset < field + 8 or offset + length != size:
        return None
    return field, offset


def _overlay_end(stream):
    stream.seek(0, 2)
    size = stream.tell()
    ends = [size]
    certificate = _pe_certificate(stream)
    if certificate:
        # Authenticode aligns the certificate to eight bytes, so there may be
        # up to seven zero padding bytes after our footer.
        ends.extend(certificate[1] - n for n in range(8))
    for end in ends:
        if end >= FOOTER_SIZE:
            stream.seek(end - len(MAGIC))
            if stream.read(len(MAGIC)) == MAGIC:
                return end
    return None


def read_overlay(path):
    with open(path, "rb") as stream:
        end = _overlay_end(stream)
        if end is None:
            return None
        stream.seek(end - FOOTER_SIZE)
        footer = stream.read(FOOTER_SIZE)
        size = struct.unpack_from("<Q", footer)[0]
        if not 0 < size <= MAX_PACKAGE or size + FOOTER_SIZE > end:
            raise FirmwareError("可执行升级包长度无效。")
        stream.seek(end - FOOTER_SIZE - size)
        data = stream.read(size)
        if hashlib.sha256(data).digest() != footer[8:40]:
            raise FirmwareError("升级包校验失败，请重新下载。")
        decode_package(data)
        return data


def _template_size(path):
    data = read_overlay(path)
    with open(path, "rb") as stream:
        if data is not None:
            return _overlay_end(stream) - len(data) - FOOTER_SIZE
        certificate = _pe_certificate(stream)
        return certificate[1] if certificate else Path(path).stat().st_size


def create_executable(template, destination, data):
    decode_package(data)
    template, destination = Path(template), Path(destination)
    if template.resolve() == destination.resolve():
        raise FirmwareError("输出文件不能覆盖制作工具自身。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".qmk-build-", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w+b") as out, template.open("rb") as source:
            certificate = _pe_certificate(source)
            left = _template_size(template)
            source.seek(0)
            while left:
                block = source.read(min(left, 1024 * 1024))
                if not block:
                    raise FirmwareError("运行模板读取不完整。")
                out.write(block)
                left -= len(block)
            if certificate:
                # A generated package is unsigned. Discard the template's
                # signature, clear its directory, and sign the final output.
                out.seek(certificate[0])
                out.write(bytes(8))
                out.seek(0, 2)
            out.write(data)
            out.write(struct.pack("<Q", len(data)) + hashlib.sha256(data).digest() + MAGIC)
        os.chmod(temp, template.stat().st_mode | 0o100)
        if read_overlay(temp) != data:
            raise FirmwareError("生成后的升级包校验失败。")
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def create_mac_app(template, destination, data):
    decode_package(data)
    template, destination = Path(template), Path(destination)
    if destination.exists() or template.resolve() == destination.resolve():
        raise FirmwareError("请选择尚不存在的 .app 输出名称。")
    shutil.copytree(str(template), str(destination), symlinks=True)
    resource = destination / "Contents" / "Resources" / "update.qmk"
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_bytes(data)
    # Adding resources changes the bundle seal. Re-sign the generated bundle.
    result = subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(destination)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise FirmwareError("macOS 升级包已生成，但临时签名失败：" + result.stderr.decode("utf-8", "replace"))


def embedded_package():
    if getattr(sys, "frozen", False):
        data = read_overlay(sys.executable)
        if data is not None:
            return decode_package(data)
        exe = Path(sys.executable)
        if sys.platform == "darwin" and exe.parent.name == "MacOS":
            external = exe.parent.parent.parent.parent / ".qmk-update"
            if external.exists():
                return decode_package(external.read_bytes())
            resource = exe.parent.parent / "Resources" / "update.qmk"
            if resource.exists():
                return decode_package(resource.read_bytes())
    return None
