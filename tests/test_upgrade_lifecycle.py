"""Progress represents verified Flash pages; each attempt exits DFU once."""
import unittest
from dataclasses import replace

from qmk_updater.package import Package, Settings
from qmk_updater.wb32 import PAGE_SIZE, UpgradeError
from qmk_updater.workflow import upgrade
from test_core import FakeClock, FakeHardware, FakeTransport, image


def opcodes(transport):
    return [command[0] for command in transport.commands if command]


class ResetRejectedTransport(FakeTransport):
    def write(self, data):
        count = super().write(data)
        if data and data[0] == 0x83:
            self.response = b"\x83\x01"
        return count


class UpgradeLifecycleTests(unittest.TestCase):
    def run_upgrade(self, hardware, settings=None, progress=None):
        clock = FakeClock()
        firmware = image(b"\x12" * (2 * PAGE_SIZE - 8))
        return upgrade(Package(settings or Settings(), firmware), hardware,
                       progress=progress or (lambda value, text: None),
                       timeout=1, clock=clock.clock, sleep=clock.sleep)

    def test_matching_boot_and_all_page_preflight_stay_at_zero(self):
        hardware = FakeHardware()
        updates = []

        def progress(value, text):
            updates.append((value, opcodes(hardware.transport)))

        result = self.run_upgrade(hardware, progress=progress)
        self.assertTrue(result.reconnected)
        self.assertEqual(updates[0][0], 0)
        preflight = [commands for value, commands in updates if value == 0]
        self.assertTrue(preflight)
        self.assertEqual(preflight[-1], [0x01, 0x72, 0x72])
        self.assertTrue(all(0x5e not in commands and 0x6a not in commands
                            for commands in preflight))
        first_value, first_commands = next(update for update in updates if update[0] > 0)
        self.assertEqual(first_value, 46)
        self.assertEqual(first_commands[-3:], [0x5e, 0x6a, 0x72])
        values = [value for value, commands in updates]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[-1], 100)

    def test_success_sends_one_boot_jump_and_one_dfu_reset(self):
        hardware = FakeHardware()
        self.assertTrue(self.run_upgrade(hardware).reconnected)
        self.assertEqual(hardware.jumps, 1)
        self.assertEqual(opcodes(hardware.transport).count(0x83), 1)
        self.assertTrue(hardware.transport.closed)

    def test_recovery_exits_dfu_once_without_sending_boot_jump(self):
        hardware = FakeHardware(apps=0, boots=1)
        self.assertTrue(self.run_upgrade(hardware, replace(Settings(), allow_boot_recovery=True)).reconnected)
        self.assertEqual(hardware.jumps, 0)
        self.assertEqual(opcodes(hardware.transport).count(0x83), 1)

    def test_preflight_and_verification_failure_never_exit_dfu(self):
        for failure in ("protected", "corrupt", "wrong_chip"):
            with self.subTest(failure=failure):
                hardware = FakeHardware()
                if failure == "wrong_chip":
                    hardware.transport.chip_id = 0
                else:
                    setattr(hardware.transport, failure, True)
                with self.assertRaises(UpgradeError):
                    self.run_upgrade(hardware)
                self.assertEqual(opcodes(hardware.transport).count(0x83), 0)
                self.assertTrue(hardware.transport.closed)

    def test_reconnect_timeout_does_not_retry_dfu_reset(self):
        hardware = FakeHardware()
        hardware.returns = False
        self.assertFalse(self.run_upgrade(hardware).reconnected)
        self.assertEqual(opcodes(hardware.transport).count(0x83), 1)
        self.assertTrue(hardware.transport.closed)

    def test_reset_error_does_not_retry_or_report_success(self):
        hardware = FakeHardware()
        hardware.transport = ResetRejectedTransport()
        updates = []
        with self.assertRaises(UpgradeError):
            self.run_upgrade(hardware, progress=lambda value, text: updates.append(value))
        self.assertEqual(opcodes(hardware.transport).count(0x83), 1)
        self.assertTrue(hardware.transport.closed)
        self.assertNotIn(100, updates)


if __name__ == "__main__":
    unittest.main()
