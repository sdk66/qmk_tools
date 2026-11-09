"""Explicit upgrade state machine, independent of the GUI and hardware APIs."""
import time
from dataclasses import dataclass

from .wb32 import Wb32, UpgradeError


@dataclass(frozen=True)
class Outcome:
    reconnected: bool
    message: str


class BootEntryError(UpgradeError):
    """APP entry failed before opening Boot; manual DFU can still continue."""

    waiting_for_manual_boot = True


def _matching_devices(hardware, settings, deadline, clock, sleep):
    # HID and USB enumeration are separate calls. A manual transition between
    # them can briefly report the old APP together with its new Boot device.
    # Rescan that mixed snapshot before rejecting two genuinely present boards.
    settle_deadline = min(deadline, clock() + 0.5)
    while True:
        apps = hardware.app_devices(settings)
        boots = hardware.boot_devices(settings)
        if len(apps) > 1 or len(boots) > 1:
            raise UpgradeError("检测到多把匹配的键盘，请仅连接一把需要升级的键盘。")
        if not (apps and boots):
            return apps, boots
        if clock() >= settle_deadline:
            raise UpgradeError("另有设备处于 Boot 模式，请拔掉其他待升级设备后重试。")
        sleep(max(0, min(0.25, settle_deadline - clock())))


def _wait_for_source(hardware, settings, deadline, clock, sleep):
    while True:
        apps, boots = _matching_devices(hardware, settings, deadline, clock, sleep)
        if apps or boots:
            return apps, boots
        if clock() >= deadline:
            raise BootEntryError("未找到匹配的键盘。请使用 USB 有线连接，并检查 VID、PID、Usage Page、Usage ID。")
        # Discovery may have started just as the customer manually entered
        # Boot. Keep the same attempt alive through that enumeration gap.
        sleep(max(0, min(0.25, deadline - clock())))


def _wait_for_boot(hardware, settings, deadline, clock, sleep, jump_error=None):
    while True:
        apps, boots = _matching_devices(hardware, settings, deadline, clock, sleep)
        if boots and not apps:
            return boots[0]
        if jump_error is not None and apps:
            raise BootEntryError(str(jump_error)) from jump_error
        if clock() >= deadline:
            if jump_error is not None:
                raise BootEntryError(str(jump_error)) from jump_error
            raise BootEntryError("等待 Boot 超时。请确认固件收到 0x0B 后执行了跳转，并检查 Boot 的 WinUSB 驱动 / USB 权限。")
        sleep(max(0, min(0.25, deadline - clock())))


def upgrade(package, hardware, progress=lambda value, text: None,
            timeout=25.0, clock=time.monotonic, sleep=time.sleep):
    package.settings.validate()
    package.firmware.validate()
    settings = package.settings
    progress(0, "正在匹配键盘的四项 HID 标识…")
    deadline = clock() + timeout
    apps, boots = _wait_for_source(hardware, settings, deadline, clock, sleep)
    if apps:
        # Re-enumerate immediately before writing Raw HID. The customer may
        # have pressed their Boot shortcut after the window's discovery pass.
        apps, boots = _wait_for_source(hardware, settings, deadline, clock, sleep)
    if boots:
        progress(0, "已检测到 DFU，直接开始升级…")
        boot = boots[0]
    else:
        progress(0, "已找到键盘，发送 0x0B 进入 Boot…")
        try:
            hardware.jump(apps[0], settings)
        except (UpgradeError, OSError) as error:
            # The HID path can disappear immediately after the last scan if
            # the customer enters Boot manually. Accept only an observed,
            # unique Boot with no APP, and never retry the 0x0B command.
            boot = _wait_for_boot(hardware, settings, clock() + timeout,
                                  clock, sleep, jump_error=error)
        else:
            boot = _wait_for_boot(hardware, settings, clock() + timeout, clock, sleep)
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
