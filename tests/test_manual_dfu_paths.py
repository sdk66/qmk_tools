"""Customers can enter DFU themselves at any point before flashing starts."""
import unittest
from dataclasses import replace

from qmk_updater.package import Package, Settings, decode_package, encode_package
from qmk_updater.session import BurnSession, Detection
from qmk_updater.wb32 import UpgradeError
from qmk_updater.workflow import BootEntryError, Outcome, upgrade
from test_core import FakeClock, FakeHardware, image


class ManualTransitionHardware(FakeHardware):
    """Simulate USB disappearance and delayed DFU enumeration without USB I/O."""

    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.app_scans = 0
        self.after_app_scan = None
        self.boot_delay = 0
        self.visible_boots = 1
        self.boot_visible_at = None
        self.jump_failure = None
        self.manual_on_jump = False
        self.keep_app = False

    def enter_boot(self):
        self.apps = 1 if self.keep_app else 0
        self.boots = 0
        self.boot_visible_at = self.clock.clock() + self.boot_delay

    def app_devices(self, settings, target=False):
        result = super().app_devices(settings, target)
        if not target and not self.transport.reset_called:
            self.app_scans += 1
            if self.app_scans == self.after_app_scan:
                self.enter_boot()
        return result

    def boot_devices(self, settings):
        if self.boot_visible_at is not None and self.clock.clock() >= self.boot_visible_at:
            self.boots = self.visible_boots
        return super().boot_devices(settings)

    def jump(self, device, settings):
        if self.jump_failure is not None:
            self.jumps += 1
            if self.manual_on_jump:
                self.enter_boot()
            raise self.jump_failure
        super().jump(device, settings)


class ManualDfuPathsTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.hardware = ManualTransitionHardware(self.clock)
        self.updates = []

    def run_upgrade(self, settings=None):
        return upgrade(Package(settings or Settings(), image()), self.hardware,
                       progress=lambda value, text: self.updates.append((value, text)),
                       timeout=1, clock=self.clock.clock, sleep=self.clock.sleep)

    def assert_flashed_once(self, jumps):
        self.assertEqual(self.hardware.jumps, jumps)
        opcodes = [command[0] for command in self.hardware.transport.commands if command]
        self.assertEqual(opcodes.count(0x83), 1)
        self.assertEqual(opcodes.count(0x5e), 1)
        self.assertTrue(self.hardware.transport.closed)
        self.assertEqual(self.updates[0][0], 0)
        self.assertEqual(self.updates[-1][0], 100)

    def assert_not_flashed(self):
        self.assertFalse(self.hardware.transport.commands)
        self.assertNotIn(100, [value for value, text in self.updates])

    def test_manual_dfu_is_default(self):
        self.assertTrue(Settings().allow_boot_recovery)
        self.hardware.enter_boot()
        self.assertTrue(self.run_upgrade().reconnected)
        self.assert_flashed_once(jumps=0)

    def test_legacy_false_setting_roundtrips_and_does_not_disable_manual_dfu(self):
        package = Package(replace(Settings(), allow_boot_recovery=False), image())
        loaded = decode_package(encode_package(package))
        self.assertFalse(loaded.settings.allow_boot_recovery)
        self.hardware.enter_boot()
        self.assertTrue(self.run_upgrade(loaded.settings).reconnected)
        self.assert_flashed_once(jumps=0)

    def test_waiting_window_accepts_manually_entered_dfu_and_starts_only_once(self):
        session = BurnSession(Settings(), self.clock.clock)
        for _ in range(3):
            self.assertEqual(session.observe(Detection()), "waiting")
        self.assertEqual(session.observe(Detection(boots=1)), "start")
        self.assertEqual(session.observe(Detection(boots=1)), "idle")
        self.assertTrue(session.begin())
        self.assertFalse(session.begin())
        self.assertEqual(session.observe(Detection(boots=1)), "idle")

    def test_manual_start_button_still_controls_manually_entered_dfu(self):
        session = BurnSession(replace(Settings(), auto_start=False,
                                      allow_boot_recovery=False), self.clock.clock)
        self.assertEqual(session.observe(Detection(boots=1)), "ready")
        self.assertFalse(session.begin())
        self.assertTrue(session.activate())
        self.assertEqual(session.observe(Detection(boots=1)), "start")
        self.assertTrue(session.begin())

    def test_app_selected_by_window_can_be_manually_entered_dfu_before_worker_starts(self):
        session = BurnSession(Settings(), self.clock.clock)
        self.assertEqual(session.observe(Detection(apps=1, targets=1)), "start")
        self.hardware.enter_boot()
        self.assertEqual(session.observe(Detection(boots=1)), "idle")
        self.assertTrue(session.begin())
        session.complete(self.run_upgrade())
        self.assertEqual(session.state, "countdown")
        self.assertEqual(session.succeeded, 1)
        self.assert_flashed_once(jumps=0)

    def test_manual_transition_between_initial_hid_and_usb_scan_is_not_two_boards(self):
        self.hardware.after_app_scan = 1
        self.assertTrue(self.run_upgrade().reconnected)
        self.assert_flashed_once(jumps=0)

    def test_final_scan_observes_manual_dfu_before_sending_boot_command(self):
        self.hardware.after_app_scan = 2
        self.assertTrue(self.run_upgrade().reconnected)
        self.assert_flashed_once(jumps=0)

    def test_manual_transition_before_final_scan_waits_through_usb_gap(self):
        self.hardware.after_app_scan = 1
        self.hardware.boot_delay = 0.5
        self.assertTrue(self.run_upgrade().reconnected)
        self.assertGreaterEqual(self.clock.clock(), 0.5)
        self.assert_flashed_once(jumps=0)

    def test_worker_starting_during_usb_gap_waits_for_manual_dfu(self):
        self.hardware.boot_delay = 0.5
        self.hardware.enter_boot()
        self.assertTrue(self.run_upgrade().reconnected)
        self.assert_flashed_once(jumps=0)

    def test_disappearing_hid_path_uses_observed_manual_dfu_without_retrying_jump(self):
        for failure in (UpgradeError("HID path disappeared"), OSError("device removed")):
            with self.subTest(failure=type(failure).__name__):
                self.setUp()
                self.hardware.jump_failure = failure
                self.hardware.manual_on_jump = True
                self.assertTrue(self.run_upgrade().reconnected)
                self.assert_flashed_once(jumps=1)

    def test_disappearing_hid_path_waits_for_delayed_manual_dfu(self):
        self.hardware.jump_failure = UpgradeError("HID path disappeared")
        self.hardware.manual_on_jump = True
        self.hardware.boot_delay = 0.5
        self.assertTrue(self.run_upgrade().reconnected)
        self.assertGreaterEqual(self.clock.clock(), 0.5)
        self.assert_flashed_once(jumps=1)

    def test_real_hid_failure_with_app_still_present_preserves_error_without_flashing(self):
        failure = UpgradeError("HID access denied")
        self.hardware.jump_failure = failure
        with self.assertRaises(BootEntryError) as raised:
            self.run_upgrade()
        self.assertIs(raised.exception.__cause__, failure)
        self.assertTrue(raised.exception.waiting_for_manual_boot)
        self.assertEqual(self.hardware.jumps, 1)
        self.assert_not_flashed()

    def test_missing_dfu_after_hid_path_disappears_preserves_error_without_retry(self):
        failure = UpgradeError("HID path disappeared")
        self.hardware.jump_failure = failure
        self.hardware.manual_on_jump = True
        self.hardware.visible_boots = 0
        with self.assertRaises(BootEntryError) as raised:
            self.run_upgrade()
        self.assertIs(raised.exception.__cause__, failure)
        self.assertEqual(self.hardware.jumps, 1)
        self.assert_not_flashed()

    def test_app_and_unrelated_dfu_still_block_flashing_after_hid_error(self):
        self.hardware.jump_failure = UpgradeError("HID access denied")
        self.hardware.manual_on_jump = True
        self.hardware.keep_app = True
        with self.assertRaises(UpgradeError):
            self.run_upgrade()
        self.assertEqual(self.hardware.jumps, 1)
        self.assert_not_flashed()

    def test_multiple_manual_dfu_devices_after_hid_disappears_block_flashing(self):
        self.hardware.jump_failure = UpgradeError("HID path disappeared")
        self.hardware.manual_on_jump = True
        self.hardware.visible_boots = 2
        with self.assertRaises(UpgradeError):
            self.run_upgrade()
        self.assertEqual(self.hardware.jumps, 1)
        self.assert_not_flashed()

    def test_stable_app_and_dfu_are_rejected_before_any_boot_command(self):
        self.hardware.boots = 1
        with self.assertRaises(UpgradeError) as raised:
            self.run_upgrade()
        self.assertFalse(getattr(raised.exception, "waiting_for_manual_boot", False))
        self.assertEqual(self.hardware.jumps, 0)
        self.assert_not_flashed()

    def test_boot_timeout_is_marked_as_entry_failure_with_no_flash_attempt(self):
        self.hardware.jump_works = False
        with self.assertRaises(BootEntryError):
            self.run_upgrade()
        self.assertEqual(self.hardware.jumps, 1)
        self.assert_not_flashed()

    def test_chip_or_flash_failure_is_not_marked_for_manual_boot_retry(self):
        for failure in ("protected", "corrupt", "wrong_chip"):
            with self.subTest(failure=failure):
                self.setUp()
                if failure == "wrong_chip":
                    self.hardware.transport.chip_id = 0
                else:
                    setattr(self.hardware.transport, failure, True)
                with self.assertRaises(UpgradeError) as raised:
                    self.run_upgrade()
                self.assertFalse(getattr(raised.exception, "waiting_for_manual_boot", False))

    def start_manual_boot_wait(self, **settings):
        session = BurnSession(replace(Settings(), **settings), self.clock.clock)
        if not session.enabled:
            self.assertTrue(session.activate())
        self.assertEqual(session.observe(Detection(apps=1)), "start")
        self.assertTrue(session.begin())
        self.assertTrue(session.wait_for_manual_boot())
        return session

    def test_entry_failure_waits_for_manual_dfu_without_retrying_app_or_counting_failure(self):
        session = self.start_manual_boot_wait()
        for _ in range(5):
            self.assertEqual(session.observe(Detection(apps=1, targets=1)), "manual_boot")
            self.assertFalse(session.begin())
        self.assertEqual((session.succeeded, session.failed), (0, 0))
        self.assertEqual(session.observe(Detection(boots=1)), "start")
        self.assertTrue(session.begin())
        self.hardware.enter_boot()
        session.complete(self.run_upgrade())
        self.assertEqual((session.succeeded, session.failed), (1, 0))
        self.assertEqual(session.state, "countdown")
        self.assert_flashed_once(jumps=0)

    def test_manual_boot_wait_respects_pause_and_multiple_device_guards(self):
        session = self.start_manual_boot_wait()
        session.paused = True
        self.assertEqual(session.observe(Detection(boots=1)), "paused")
        session.paused = False
        for detection in (Detection(boots=2), Detection(apps=1, boots=1),
                          Detection(targets=1, boots=1)):
            self.assertEqual(session.observe(detection), "multiple")
        self.assertEqual(session.state, "manual_boot")
        self.assertEqual(session.observe(Detection(boots=1)), "start")

    def test_single_manual_start_requires_new_click_after_stable_removal(self):
        session = self.start_manual_boot_wait(auto_start=False)
        self.assertEqual(session.observe(Detection()), "manual_boot")
        self.clock.sleep(0.7)
        self.assertEqual(session.observe(Detection()), "next")
        self.assertEqual(session.observe(Detection(boots=1)), "ready")
        self.assertFalse(session.enabled)

    def test_continuous_station_stays_activated_after_stable_removal(self):
        session = self.start_manual_boot_wait(auto_start=False, burn_mode="continuous")
        self.assertEqual(session.observe(Detection()), "manual_boot")
        self.clock.sleep(0.7)
        self.assertEqual(session.observe(Detection()), "next")
        self.assertEqual(session.observe(Detection(apps=1)), "start")

    def test_explicit_retry_can_retry_app_after_entry_failure(self):
        session = self.start_manual_boot_wait()
        self.assertTrue(session.retry())
        self.assertEqual(session.observe(Detection(apps=1)), "start")

    def test_flash_failure_and_reconnect_warning_still_block_manual_dfu(self):
        for outcome, error, state in ((None, "write failed", "failed"),
                                      (Outcome(False, "not reconnected"), "", "warning")):
            with self.subTest(state=state):
                session = BurnSession(Settings(), self.clock.clock)
                self.assertEqual(session.observe(Detection(boots=1)), "start")
                self.assertTrue(session.begin())
                session.complete(outcome, error)
                self.assertEqual(session.state, state)
                self.assertEqual(session.observe(Detection(boots=1)), "blocked")


if __name__ == "__main__":
    unittest.main()
