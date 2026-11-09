"""WB32 USB Bulk protocol, ported from WestberryTech/wb32-dfu-updater.

Derived from dfufwdevice.c and dfufw.c, copyright (C) 2021 Westberry
Technology (ChangZhou) Corp., Ltd, licensed under Apache-2.0.
Changes: Python transport, strict response/range checks, no automatic removal
of read protection, sparse page preservation and progress callbacks.
"""
import struct
from dataclasses import dataclass

from .firmware import FLASH_BASE, MAX_FLASH, FirmwareError

PAGE_SIZE = 256


class UpgradeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChipInfo:
    boot_version: int
    chip_id: int
    flash_size: int
    sram_size: int


class Wb32:
    def __init__(self, transport):
        self.transport = transport

    def exchange(self, command, response_length=None):
        written = self.transport.write(command)
        if written != len(command):
            raise UpgradeError("USB 命令未完整发送。")
        if len(command) % self.transport.packet_size == 0:
            if self.transport.write(b"") != 0:
                raise UpgradeError("USB 零长度包发送失败。")
        response = bytes(self.transport.read(1024))
        if len(response) < 2:
            raise UpgradeError("Boot 返回的数据不完整。")
        if response[1] == 0x1a:
            raise UpgradeError("芯片启用了读保护，已停止升级。请由厂家处理读保护设置后再试。")
        if response[1]:
            raise UpgradeError("WB32 命令 0x%02X 失败（状态 0x%02X）。" % (command[0], response[1]))
        if response_length is not None and len(response) != response_length:
            raise UpgradeError("Boot 响应长度错误：预期 %d，实际 %d。" % (response_length, len(response)))
        return response

    def info(self):
        response = self.exchange(b"\x01\x00", 16)
        if response[2] != 13:
            raise UpgradeError("WB32 芯片信息长度错误。")
        boot, chip, flash, ram = struct.unpack_from("<BIII", response, 3)
        if chip & 0x3fff != 0x2980:
            raise UpgradeError("芯片 ID 0x%08X 不受支持。" % chip)
        if flash != MAX_FLASH or ram != 36 * 1024:
            raise UpgradeError("芯片存储规格与 WB32FQ95 不符（Flash %d KiB / SRAM %d KiB）。" % (flash // 1024, ram // 1024))
        return ChipInfo(boot, chip, flash, ram)

    def read(self, address, count):
        result = bytearray()
        while len(result) < count:
            n = min(256, count - len(result))
            command = struct.pack("<B3xIH", 0x72, address + len(result), n)
            result.extend(self.exchange(command, n + 2)[2:])
        return bytes(result)

    def erase_page(self, address):
        self.exchange(struct.pack("<B3xII", 0x5e, address, 1), 2)

    def program_page(self, address, data):
        if address % PAGE_SIZE or len(data) != PAGE_SIZE:
            raise UpgradeError("Flash 页地址或长度无效。")
        self.exchange(struct.pack("<B3xII", 0x6a, address, len(data)) + data, 2)

    def reset(self):
        self.exchange(struct.pack("<B3xI", 0x83, 1000), 2)

    def flash(self, firmware, progress=lambda value, text: None):
        firmware.validate()
        info = self.info()
        sp = struct.unpack_from("<I", firmware.segments[0].data)[0]
        if sp > 0x20000000 + info.sram_size:
            raise UpgradeError("固件初始栈地址超出实际 SRAM 范围。")
        pages = {}
        for segment in firmware.segments:
            if segment.address < FLASH_BASE or segment.address + len(segment.data) > FLASH_BASE + info.flash_size:
                raise UpgradeError("固件超过实际芯片 Flash 范围。")
            for index, value in enumerate(segment.data):
                address = segment.address + index
                page_address = address & ~(PAGE_SIZE - 1)
                pages.setdefault(page_address, {})[address - page_address] = value
        progress(12, "已识别 WB32FQ95 · Flash 256 KiB / SRAM 36 KiB")
        # Read every affected page before the first erase. A read-protected chip
        # or unreadable page therefore never triggers a partial download.
        prepared = []
        for index, (address, changes) in enumerate(sorted(pages.items())):
            old = self.read(address, PAGE_SIZE)
            new = bytearray(old)
            for offset, value in changes.items():
                new[offset] = value
            prepared.append((address, old, bytes(new)))
            progress(12 + int(12 * (index + 1) / len(pages)), "检查 Flash · %d / %d 页" % (index + 1, len(pages)))
        for index, (address, old, new) in enumerate(prepared):
            if old != new:
                self.erase_page(address)
                self.program_page(address, new)
            if self.read(address, PAGE_SIZE) != new:
                raise UpgradeError("读回校验失败：0x%08X。设备保留在 Boot 模式，请重新升级。" % address)
            progress(24 + int(69 * (index + 1) / len(prepared)), "写入并校验 · %d / %d 页" % (index + 1, len(prepared)))
        return info
