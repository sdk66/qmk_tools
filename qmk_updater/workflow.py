"""Explicit upgrade state machine, independent of the GUI and hardware APIs."""
import time
from dataclasses import dataclass

from .wb32 import Wb32, UpgradeError


@dataclass(frozen=True)
class Outcome:
    reconnected: bool
    message: str


def upgrade(package, hardware, progress=lambda value, text: None,
            timeout=25.0, clock=time.monotonic, sleep=time.sleep):
    package.settings.validate()
    package.firmware.validate()
    settings = package.settings
    progress(0, "正在匹配键盘的四项 HID 标识…")
    apps = hardware.app_devices(settings)
    boots = hardware.boot_devices(settings)
    if len(apps) > 1 or len(boots) > 1:
        raise UpgradeError("检测到多把匹配的键盘，请仅连接一把需要升级的键盘。")
    if apps and boots:
        raise UpgradeError("另有设备处于 Boot 模式，请拔掉其他待升级设备后重试。")
    if not apps:
        if not boots:
            raise UpgradeError("未找到匹配的键盘。请使用 USB 有线连接，并检查 VID、PID、Usage Page、Usage ID。")
        if not settings.allow_boot_recovery:
            raise UpgradeError("键盘已在 Boot 模式，此升级包未开启恢复升级。请由厂家生成允许 Boot 恢复的包。")
        progress(0, "恢复升级：已找到唯一的 Boot 设备")
        boot = boots[0]
    else:
        progress(0, "已找到键盘，发送 0x0B 进入 Boot…")
        hardware.jump(apps[0], settings)
        deadline = clock() + timeout
        boot = None
        app_disappeared = False
        while clock() < deadline:
            sleep(0.25)
            current_apps = hardware.app_devices(settings)
            current_boots = hardware.boot_devices(settings)
            if len(current_boots) > 1 or len(current_apps) > 1:
                raise UpgradeError("切换期间出现多个匹配设备，已停止升级。请仅保留目标键盘。")
            if not current_apps:
                app_disappeared = True
            if current_boots and app_disappeared and not current_apps:
                boot = current_boots[0]
                break
        if boot is None:
            raise UpgradeError("等待 Boot 超时。请确认固件收到 0x0B 后执行了跳转，并检查 Boot 的 WinUSB 驱动 / USB 权限。")
    progress(0, "Boot 已连接，正在检查芯片…")
    transport = hardware.open_boot(boot)
    try:
        flasher = Wb32(transport)
        flasher.flash(package.firmware, progress)
        progress(95, "全部页面校验通过，正在退出 DFU…")
        # This is the sole reboot command for an attempt. Closing the USB
        # transport and waiting for APP below must never send another reset.
        flasher.reset()
    finally:
        transport.close()
    deadline = clock() + timeout
    while clock() < deadline:
        sleep(0.3)
        targets = hardware.app_devices(settings, target=True)
        # A delayed reboot must not be mistaken for an APP return if the same
        # VID/PID was already present in another process's discovery cache.
        if len(targets) == 1 and not hardware.boot_devices(settings):
            progress(100, "升级完成，键盘已重新连接")
            return Outcome(True, "固件已写入并通过逐页读回校验，键盘已重新连接。")
    progress(98, "固件校验通过，尚未检测到键盘重新连接")
    return Outcome(False, "固件已写入并通过读回校验，但未检测到新固件的 HID 接口。请重新插拔键盘；若仍未恢复，请联系厂家。")
