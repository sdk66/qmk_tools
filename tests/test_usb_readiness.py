"""Boot opening can settle without replaying entry, Flash, or reset commands."""
import unittest
from unittest.mock import patch

import usb.core

from qmk_updater.devices import BootAccessError, UsbTransport
from qmk_updater.package import Package, Settings
from qmk_updater.wb32 import UpgradeError
from qmk_updater.workflow import BOOT_READY_TIMEOUT, upgrade
from test_core import FakeClock, FakeHardware, image


class OpeningDevice:
    bMaxPacketSize0 = 64
    bNumConfigurations = 1

    def __init__(self, error):
        self.error = error

    def get_active_configuration(self):
        raise self.error


class BootAccessTests(unittest.TestCase):
    def failure(self, original, platform="win32", cleanup_error=None):
        with patch("qmk_updater.devices.sys.platform", platform), \
                patch("usb.util.dispose_resources", side_effect=cleanup_error) as dispose:
            with self.assertRaises(BootAccessError) as raised:
                UsbTransport(OpeningDevice(original))
        dispose.assert_called_once()
        self.assertIs(raised.exception.__cause__, original)
        return raised.exception

    def test_busy_is_retryable_and_does_not_claim_driver_missing(self):
        error = self.failure(usb.core.USBError("busy", -6, 16))
        self.assertTrue(error.retryable)
        self.assertIn("占用", str(error))
        self.assertIn("libusb -6", str(error))
        self.assertNotIn("WinUSB", str(error))

    def test_pyusb_not_supported_is_retryable_with_conditional_driver_advice(self):
        error = self.failure(NotImplementedError("Operation not supported"))
        self.assertTrue(error.retryable)
        self.assertIn("若重新连接后仍失败", str(error))
        self.assertIn("WinUSB", str(error))
        self.assertNotIn("请先为", str(error))

    def test_transient_libusb_errors_are_retryable(self):
        for code in (-1, -3, -4, -5, -7, -10):
            with self.subTest(code=code):
                error = self.failure(usb.core.USBError("USB failed", code))
                self.assertTrue(error.retryable)
                self.assertNotIn("WinUSB", str(error))

    def test_invalid_operation_and_resource_errors_do_not_retry(self):
        for code in (-2, -8, -9, -11, -99, None):
            with self.subTest(code=code):
                error = self.failure(usb.core.USBError("USB failed", code))
                self.assertFalse(error.retryable)

    def test_unexpected_failure_is_not_misreported_as_missing_driver(self):
        error = self.failure(ValueError("bad descriptor"))
        self.assertFalse(error.retryable)
        self.assertNotIn("WinUSB", str(error))

    def test_linux_access_denial_keeps_udev_advice(self):
        error = self.failure(usb.core.USBError("denied", -3, 13), "linux")
        self.assertTrue(error.retryable)
        self.assertIn("udev", str(error))

    def test_cleanup_removal_does_not_hide_original_open_error(self):
        original = usb.core.USBError("removed", -4, 19)
        error = self.failure(original, cleanup_error=usb.core.USBError("cleanup failed", -4))
        self.assertTrue(error.retryable)
        self.assertIn("连接已断开", str(error))

    def test_wrong_boot_descriptor_is_an_immediate_validation_error(self):
        device = OpeningDevice(None)
        device.bNumConfigurations = 2
        device.get_active_configuration = lambda: type("Config", (), {"bNumInterfaces": 1})()
        with patch("usb.util.dispose_resources") as dispose:
            with self.assertRaises(UpgradeError) as raised:
                UsbTransport(device)
        self.assertNotIsInstance(raised.exception, BootAccessError)
        self.assertIn("配置", str(raised.exception))
        dispose.assert_called_once_with(device)


class ReadinessHardware(FakeHardware):
    def __init__(self, clock, apps=1, boots=0, failures=2):
        super().__init__(apps, boots)
        self.clock = clock
        self.failures = failures
        self.opened = []
        self.scans = 0
        self.on_failure = None
        self.reappear_at = None
        self.failure = BootAccessError("Boot USB 尚未就绪", retryable=True)

    def boot_devices(self, settings):
        if self.reappear_at is not None and self.clock.clock() >= self.reappear_at:
            self.boots = 1
        self.scans += 1
        return [] if self.transport.reset_called else ["boot-%d" % self.scans] * self.boots

    def open_boot(self, device):
        self.opened.append(device)
        if len(self.opened) <= self.failures:
            if self.transport.commands:
                raise AssertionError("A readiness retry must precede every firmware command")
            if self.on_failure:
                self.on_failure()
            raise self.failure
        return self.transport


class BootReadinessWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.hardware = ReadinessHardware(self.clock)
        self.updates = []

    def run_upgrade(self, timeout=1):
        return upgrade(Package(Settings(), image()), self.hardware,
                       progress=lambda value, text: self.updates.append((value, text)),
                       timeout=timeout, clock=self.clock.clock, sleep=self.clock.sleep)

    def opcodes(self):
        return [data[0] for data in self.hardware.transport.commands if data]

    def assert_single_flash(self, jumps):
        self.assertEqual(self.hardware.jumps, jumps)
        self.assertEqual(self.opcodes().count(0x5e), 1)
        self.assertEqual(self.opcodes().count(0x6a), 1)
        self.assertEqual(self.opcodes().count(0x83), 1)

    def test_automatic_entry_retries_fresh_boot_handles_then_flashes_once(self):
        self.assertTrue(self.run_upgrade().reconnected)
        self.assertEqual(len(self.hardware.opened), 3)
        self.assertEqual(len(set(self.hardware.opened)), 3)
        self.assert_single_flash(jumps=1)
        waiting = [(value, text) for value, text in self.updates if "等待 USB" in text]
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0][0], 0)

    def test_manual_dfu_has_the_same_readiness_retry_without_hid_entry(self):
        self.hardware.apps, self.hardware.boots = 0, 1
        self.assertTrue(self.run_upgrade().reconnected)
        self.assert_single_flash(jumps=0)

    def test_ready_device_has_no_extra_open_delay(self):
        self.hardware.failures = 0
        self.assertTrue(self.run_upgrade().reconnected)
        self.assertEqual(len(self.hardware.opened), 1)
        self.assertAlmostEqual(self.clock.now, 0.3)

    def test_driver_reenumeration_gap_is_waited_without_a_stale_handle(self):
        self.hardware.failures = 1

        def disappear():
            self.hardware.boots = 0
            self.hardware.reappear_at = 0.5

        self.hardware.on_failure = disappear
        self.assertTrue(self.run_upgrade().reconnected)
        self.assertEqual(len(self.hardware.opened), 2)
        self.assertGreaterEqual(self.clock.now, 0.8)
        self.assert_single_flash(jumps=1)

    def test_readiness_failure_is_bounded_by_the_existing_short_timeout(self):
        self.hardware.failures = 1000
        with self.assertRaises(BootAccessError) as raised:
            self.run_upgrade()
        self.assertIs(raised.exception, self.hardware.failure)
        self.assertAlmostEqual(self.clock.now, 1)
        self.assertFalse(self.opcodes())
        self.assertEqual(self.hardware.jumps, 1)

    def test_default_readiness_budget_never_exceeds_five_seconds(self):
        self.hardware.failures = 1000
        with self.assertRaises(BootAccessError):
            self.run_upgrade(timeout=25)
        self.assertAlmostEqual(self.clock.now, BOOT_READY_TIMEOUT)
        self.assertFalse(self.opcodes())

    def test_unplugged_boot_is_not_opened_repeatedly_or_programmed(self):
        self.hardware.on_failure = lambda: setattr(self.hardware, "boots", 0)
        with self.assertRaises(BootAccessError):
            self.run_upgrade()
        self.assertEqual(len(self.hardware.opened), 1)
        self.assertFalse(self.opcodes())

    def test_multiple_boot_devices_appearing_during_retry_block_flash(self):
        self.hardware.on_failure = lambda: setattr(self.hardware, "boots", 2)
        with self.assertRaises(UpgradeError) as raised:
            self.run_upgrade()
        self.assertIn("多把", str(raised.exception))
        self.assertEqual(len(self.hardware.opened), 1)
        self.assertFalse(self.opcodes())

    def test_app_plus_unrelated_boot_during_retry_block_flash(self):
        self.hardware.on_failure = lambda: setattr(self.hardware, "apps", 1)
        with self.assertRaises(UpgradeError) as raised:
            self.run_upgrade()
        self.assertIn("另有设备", str(raised.exception))
        self.assertEqual(len(self.hardware.opened), 1)
        self.assertFalse(self.opcodes())

    def test_nonretryable_open_failure_stops_immediately(self):
        for failure in (UpgradeError("wrong Boot descriptors"),
                        BootAccessError("invalid operation", retryable=False)):
            with self.subTest(failure=str(failure)):
                self.setUp()
                self.hardware.failure = failure
                with self.assertRaises(UpgradeError) as raised:
                    self.run_upgrade()
                self.assertIs(raised.exception, failure)
                self.assertEqual(len(self.hardware.opened), 1)
                self.assertEqual(self.clock.now, 0)
                self.assertFalse(self.opcodes())

    def test_flash_failure_is_never_retried_by_readiness_loop(self):
        self.hardware.transport.corrupt = True
        with self.assertRaises(UpgradeError):
            self.run_upgrade()
        self.assertEqual(len(self.hardware.opened), 3)
        self.assertEqual(self.opcodes().count(0x5e), 1)
        self.assertEqual(self.opcodes().count(0x6a), 1)
        self.assertNotIn(0x83, self.opcodes())
        self.assertTrue(self.hardware.transport.closed)


if __name__ == "__main__":
    unittest.main()
