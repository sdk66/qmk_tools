"""Strict Intel HEX parsing and conservative USB descriptor discovery."""
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List

FLASH_BASE = 0x08000000
MAX_FLASH = 256 * 1024  # WB32FQ95; the device is checked again before writing.


class FirmwareError(ValueError):
    pass


@dataclass(frozen=True)
class Segment:
    address: int
    data: bytes


@dataclass(frozen=True)
class UsbIdentity:
    vid: int
    pid: int
    version: int
    address: int
    usb_version: int = 0x0200


@dataclass(frozen=True)
class HidIdentity:
    usage_page: int
    usage: int
    report_size: int
    report_id: int
    address: int


@dataclass
class Firmware:
    name: str
    segments: List[Segment]
    source_sha256: str

    @property
    def size(self):
        return sum(len(s.data) for s in self.segments)

    @property
    def base(self):
        return self.segments[0].address

    @property
    def end(self):
        last = self.segments[-1]
        return last.address + len(last.data)

    def validate(self):
        if not self.segments or not self.size:
            raise FirmwareError("固件为空。")
        previous_end = FLASH_BASE
        for s in self.segments:
            if not s.data or s.address < previous_end or s.address + len(s.data) > FLASH_BASE + MAX_FLASH:
                raise FirmwareError("固件地址重叠或超出 Q95 的 0x08000000–0x0803FFFF 范围。")
            previous_end = s.address + len(s.data)
        if len(self.segments[0].data) < 8:
            raise FirmwareError("固件缺少 ARM 向量表。")
        sp, reset = struct.unpack_from("<II", self.segments[0].data)
        if not 0x20000000 < sp <= 0x20010000 or sp % 4:
            raise FirmwareError("ARM 初始栈地址无效，请确认是 Q95 的 APP 固件。")
        if not reset & 1 or not any(s.address <= (reset & ~1) < s.address + len(s.data) for s in self.segments):
            raise FirmwareError("ARM 复位向量无效或指向固件范围之外。")

    def usb_candidates(self):
        result = []
        for s in self.segments:
            for i in range(len(s.data) - 17):
                b = s.data[i:i + 18]
                if (b[:2] == b"\x12\x01" and b[7] in (8, 16, 32, 64)
                        and struct.unpack_from("<H", b, 2)[0] in (0x110, 0x200, 0x201, 0x210, 0x300)
                        and 1 <= b[17] <= 4):
                    vid, pid, ver = struct.unpack_from("<HHH", b, 8)
                    if vid not in (0, 0xffff) and pid not in (0, 0xffff):
                        result.append(UsbIdentity(vid, pid, ver, s.address + i, struct.unpack_from("<H", b, 2)[0]))
        return result

    def hid_candidates(self):
        result = []
        for s in self.segments:
            for i in range(len(s.data) - 8):
                # A vendor Usage Page begins every QMK Raw HID descriptor.
                if s.data[i] != 0x06 or s.data[i + 2] != 0xff:
                    continue
                candidate = _parse_hid(s.data[i:i + 1024], s.address + i)
                if candidate and candidate not in result:
                    result.append(candidate)
        return result

    def strings(self):
        result = []
        descriptors = [u.address for u in self.usb_candidates()]
        for s in self.segments:
            b = s.data
            for i in range(len(b) - 3):
                if not any(abs(s.address + i - address) < 1024 for address in descriptors):
                    continue
                length = b[i]
                if b[i + 1] != 3 or length < 6 or length > 128 or length % 2 or i + length > len(b):
                    continue
                try:
                    value = b[i + 2:i + length].decode("utf-16-le")
                except UnicodeDecodeError:
                    continue
                if (len(value) >= 3 and all(32 <= ord(c) < 127 or 0x4e00 <= ord(c) <= 0x9fff for c in value)
                        and any(c.isalpha() for c in value) and value not in result):
                    result.append(value)
        return result


def _parse_hid(data, address):
    page = usage = report_id = count = bits = 0
    depth = 0
    application = None
    outputs = []
    has_input = False
    pos = 0
    stack = []
    while pos < len(data):
        prefix = data[pos]
        if prefix == 0xfe:
            return None
        length = (0, 1, 2, 4)[prefix & 3]
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        if pos + 1 + length > len(data):
            return None
        value = int.from_bytes(data[pos + 1:pos + 1 + length], "little")
        pos += 1 + length
        if kind == 1:
            if tag == 0:
                page = value
            elif tag == 7:
                bits = value
            elif tag == 8:
                report_id = value
            elif tag == 9:
                count = value
            elif tag == 10:
                stack.append((page, report_id, count, bits))
            elif tag == 11:
                if not stack:
                    return None
                page, report_id, count, bits = stack.pop()
        elif kind == 2 and tag == 0:
            usage = value
        elif kind == 0:
            if tag == 10:
                if depth == 0:
                    if value != 1 or page < 0xff00:
                        return None
                    application = (page, usage)
                depth += 1
            elif tag == 8 and depth:
                has_input = True
            elif tag == 9 and depth:
                if bits != 8 or not 1 <= count <= 1024 or report_id > 255:
                    return None
                outputs.append((count, report_id))
            elif tag == 12:
                depth -= 1
                if depth == 0:
                    if application and has_input and len(outputs) == 1:
                        size, rid = outputs[0]
                        return HidIdentity(application[0], application[1], size, rid, address)
                    return None
                if depth < 0:
                    return None
    return None


def load_firmware(path, bin_base=FLASH_BASE):
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise FirmwareError("文件过大，不是受支持的 Q95 固件。")
    suffix = path.suffix.lower()
    if suffix == ".bin":
        segments = [Segment(bin_base, raw)]
    elif suffix == ".hex":
        segments = parse_hex(raw)
    else:
        raise FirmwareError("请选择 .hex 或 .bin 固件。")
    firmware = Firmware(path.name, segments, hashlib.sha256(raw).hexdigest())
    firmware.validate()
    return firmware


def parse_hex(raw):
    memory = {}
    upper = 0
    eof = False
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError:
        raise FirmwareError("HEX 必须是 ASCII 文本。")
    for number, text in enumerate(lines, 1):
        text = text.strip()
        if not text:
            continue
        if eof:
            raise FirmwareError("HEX 结束记录后仍有数据（第 %d 行）。" % number)
        try:
            if not text.startswith(":"):
                raise ValueError()
            record = bytes.fromhex(text[1:])
            if len(record) < 5 or len(record) != record[0] + 5 or sum(record) % 256:
                raise ValueError()
        except ValueError:
            raise FirmwareError("HEX 第 %d 行格式或校验和错误。" % number)
        count = record[0]
        address = int.from_bytes(record[1:3], "big")
        kind = record[3]
        data = record[4:-1]
        if kind == 0:
            if address + count > 65536:
                raise FirmwareError("HEX 数据记录跨越 64 KiB 边界。")
            for offset, value in enumerate(data):
                a = upper + address + offset
                if not FLASH_BASE <= a < FLASH_BASE + MAX_FLASH or a in memory:
                    raise FirmwareError("HEX 地址越界或重复：0x%08X。" % a)
                memory[a] = value
        elif kind == 1 and count == 0 and address == 0:
            eof = True
        elif kind in (2, 4) and count == 2 and address == 0:
            upper = int.from_bytes(data, "big") << (4 if kind == 2 else 16)
        elif kind in (3, 5) and count == 4 and address == 0:
            pass  # Execution address records do not contain flash data.
        else:
            raise FirmwareError("HEX 第 %d 行的记录类型或长度不受支持。" % number)
    if not eof or not memory:
        raise FirmwareError("HEX 缺少结束记录或固件内容。")
    segments = []
    start = previous = None
    data = bytearray()
    for address in sorted(memory):
        if previous is not None and address != previous + 1:
            segments.append(Segment(start, bytes(data)))
            data.clear()
            start = None
        if start is None:
            start = address
        data.append(memory[address])
        previous = address
    segments.append(Segment(start, bytes(data)))
    return segments
