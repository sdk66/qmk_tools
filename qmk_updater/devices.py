"""HID discovery and libusb transport. Importing this module never writes USB."""
import sys

from .wb32 import UpgradeError


class BootAccessError(UpgradeError):
    """Opening/claiming Boot failed before any firmware commands were sent."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def _boot_access_error(error):
    import usb.core

    # PyUSB 1.2 maps LIBUSB_ERROR_NOT_SUPPORTED to NotImplementedError,
    # while the other libusb failures retain their backend_error_code.
    code = (-12 if isinstance(error, NotImplementedError)
            else getattr(error, "backend_error_code", None))
    usb_error = isinstance(error, (usb.core.USBError, NotImplementedError))
    retryable = usb_error and code in (-1, -3, -4, -5, -6, -7, -10, -12)
    if sys.platform == "win32" and code == -12:
        message = ("Boot USB 接口尚未就绪或驱动不兼容。若重新连接后仍失败，"
                   "请检查 WB Device in DFU Mode 的 WinUSB 驱动。")
    elif code == -6:
        message = "Boot USB 接口正被占用，请关闭其他键盘升级工具后重试。"
    elif code == -4:
        message = "Boot USB 连接已断开，请检查 USB 数据线并重新连接键盘。"
    elif sys.platform.startswith("linux") and code == -3:
        message = "Boot USB 访问被拒绝，请安装升级包中的 Linux udev 规则后重新插拔键盘。"
    elif code == -3:
        message = "Boot USB 访问被拒绝，请关闭其他键盘工具并检查 USB 访问权限。"
    else:
        message = "无法打开 Boot USB 接口，请检查 USB 连接并关闭其他键盘工具后重试。"
    detail = str(error)
    if code is not None:
        detail += " (libusb %d)" % code
    return BootAccessError(message + "原始错误：" + detail, retryable=retryable)


def usb_backend():
    import usb.backend.libusb1
    import libusb_package
    backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    if backend is None and sys.platform.startswith("linux"):
        # Linux distributions can provide libusb independently of the wheel.
        backend = usb.backend.libusb1.get_backend()
    if backend is None:
        if sys.platform.startswith("linux"):
            raise UpgradeError("USB 服务未就绪，请检查 USB 连接和系统 libusb；虚拟机需启用 USB 直通。")
        raise UpgradeError("USB 后端无法加载，请使用完整的官方升级包。")
    return backend


class Hardware:
    def __init__(self):
        self._backend = None

    def app_devices(self, settings, target=False):
        import hid
        prefix = "target_" if target else "app_"
        vid, pid = getattr(settings, prefix + "vid"), getattr(settings, prefix + "pid")
        page = settings.target_usage_page if target else settings.usage_page
        usage = settings.target_usage_id if target else settings.usage_id
        return [d for d in hid.enumerate(vid, pid)
                if d.get("usage_page") == page and d.get("usage") == usage]

    def boot_devices(self, settings):
        import usb.core
        if self._backend is None:
            self._backend = usb_backend()
        return list(usb.core.find(find_all=True, idVendor=settings.boot_vid,
                                  idProduct=settings.boot_pid, backend=self._backend))

    def jump(self, device, settings):
        import hid
        handle = hid.device()
        try:
            handle.open_path(device["path"])
            # HIDAPI requires a report-ID byte even for unnumbered reports.
            # The first byte delivered to via_command_kb(data, length) is 0x0B.
            report = bytes([settings.report_id, 0x0b]) + bytes(settings.report_size - 1)
            if handle.write(report) != len(report):
                raise UpgradeError("0x0B 进 Boot 命令未完整发送。请关闭其他键盘驱动后重试。")
        except OSError as e:
            raise UpgradeError("Raw HID 发送失败：%s。请关闭 VIA / 键盘驱动后重试。" % e)
        finally:
            handle.close()

    def open_boot(self, device):
        return UsbTransport(device)


class UsbTransport:
    def __init__(self, device):
        import usb.util
        self.device = device
        self.claimed = False
        try:
            self.packet_size = int(device.bMaxPacketSize0)
            config = device.get_active_configuration()
            if config is None:
                device.set_configuration()
                config = device.get_active_configuration()
            if device.bNumConfigurations != 1 or config.bNumInterfaces != 1:
                raise UpgradeError("Boot USB 配置与 WB32 不符。")
            interface = config[(0, 0)]
            endpoints = {ep.bEndpointAddress: ep for ep in interface}
            if (interface.bInterfaceClass != 0xff or interface.bInterfaceSubClass != 0xff
                    or set(endpoints) != {0x81, 0x01}
                    or any((ep.bmAttributes & 3) != 2 for ep in endpoints.values())):
                raise UpgradeError("目标 Boot 不是 WB32 USB Bulk 设备。")
            manufacturer = usb.util.get_string(device, device.iManufacturer)
            product = usb.util.get_string(device, device.iProduct)
            if manufacturer != "Westberry Tech." or product != "WB Device in DFU Mode":
                raise UpgradeError("Boot 厂商或产品描述符与 WB32 不符。")
            if self.packet_size not in (8, 16, 32, 64):
                raise UpgradeError("Boot USB 包大小无效。")
            self.interface = interface.bInterfaceNumber
            usb.util.claim_interface(device, self.interface)
            self.claimed = True
        except Exception as e:
            self.close()
            if isinstance(e, UpgradeError):
                raise
            raise _boot_access_error(e) from e

    def write(self, data):
        return self.device.write(0x01, data, timeout=5000)

    def read(self, count):
        return self.device.read(0x81, count, timeout=5000)

    def close(self):
        import usb.util
        if self.claimed:
            try:
                usb.util.release_interface(self.device, self.interface)
            except Exception:
                pass
            self.claimed = False
        try:
            usb.util.dispose_resources(self.device)
        except Exception:
            # Removal during the handover must not hide the original error.
            pass
