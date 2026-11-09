import io
import json
import unittest
import zipfile
from dataclasses import replace

from qmk_updater.package import Settings, Package, encode_package, decode_package
from qmk_updater.session import BurnSession, Detection
from qmk_updater.workflow import Outcome
from test_core import FakeClock, image


class SessionTests(unittest.TestCase):
    def make_session(self, continuous=False, **kwargs):
        self.clock = FakeClock()
        return BurnSession(replace(Settings(), burn_mode="continuous" if continuous else "single", **kwargs), self.clock.clock)

    def successful_attempt(self, session):
        self.assertEqual(session.observe(Detection(apps=1, targets=1)), "start")
        self.assertTrue(session.begin())
        session.complete(Outcome(True, "reconnected"))

    def test_single_automatically_starts_and_closes_after_exactly_five_seconds(self):
        session = self.make_session()
        self.successful_attempt(session)
        self.assertEqual(session.state, "countdown")
        self.assertEqual(session.remaining(), 5)
        for expected in (4, 3, 2, 1, 0):
            self.clock.sleep(1)
            self.assertEqual(session.remaining(), expected)
        self.assertEqual(session.observe(Detection(apps=1, targets=1)), "idle")
        self.assertEqual(session.succeeded, 1)

    def test_single_error_never_starts_countdown_or_automatically_retries_same_board(self):
        session = self.make_session()
        session.observe(Detection(apps=1))
        session.begin()
        session.complete(error="write failed")
        self.assertIsNone(session.remaining())
        for _ in range(10):
            self.clock.sleep(1)
            self.assertEqual(session.observe(Detection(apps=1)), "blocked")
        self.assertEqual(session.failed, 1)
        self.assertTrue(session.retry())
        self.assertEqual(session.observe(Detection(apps=1)), "start")

    def test_reconnect_warning_never_auto_closes(self):
        session = self.make_session()
        session.observe(Detection(apps=1))
        session.begin()
        session.complete(Outcome(False, "not reconnected"))
        self.clock.sleep(100)
        self.assertEqual(session.state, "warning")
        self.assertIsNone(session.remaining())
        self.assertEqual(session.succeeded, 0)

    def test_factory_waits_for_all_interfaces_to_disappear_before_next_board(self):
        session = self.make_session(True, target_pid=0x1234)
        self.assertEqual(session.observe(Detection(apps=1)), "start")
        session.begin()
        session.complete(Outcome(True, "done"))
        for detection in (Detection(targets=1), Detection(apps=1), Detection(boots=1)) * 5:
            self.clock.sleep(1)
            self.assertEqual(session.observe(detection), "remove")
        self.assertEqual(session.observe(Detection()), "remove")
        self.clock.sleep(.7)
        self.assertEqual(session.observe(Detection()), "next")
        self.assertEqual(session.observe(Detection(apps=1)), "start")
        session.begin()
        session.complete(Outcome(True, "done"))
        self.assertEqual(session.succeeded, 2)
        self.assertEqual(session.state, "remove")
        self.assertIsNone(session.remaining())

    def test_brief_missing_detection_does_not_rearm_factory(self):
        session = self.make_session(True)
        self.successful_attempt(session)
        self.assertEqual(session.observe(Detection()), "remove")
        self.clock.sleep(.1)
        self.assertEqual(session.observe(Detection()), "remove")
        self.assertEqual(session.observe(Detection(targets=1)), "remove")
        self.clock.sleep(10)
        self.assertEqual(session.observe(Detection()), "remove")
        self.assertEqual(session.state, "remove")

    def test_factory_failure_can_be_removed_and_next_board_automatically_processed(self):
        session = self.make_session(True)
        session.observe(Detection(apps=1))
        session.begin()
        session.complete(error="verification failed")
        self.assertEqual(session.observe(Detection(boots=1)), "blocked")
        session.observe(Detection())
        self.clock.sleep(.7)
        self.assertEqual(session.observe(Detection()), "next")
        self.assertEqual(session.observe(Detection(apps=1)), "start")
        self.assertEqual(session.failed, 1)

    def test_multiple_devices_never_arm(self):
        session = self.make_session(True)
        for detection in (Detection(apps=2), Detection(boots=2), Detection(apps=1, boots=1),
                          Detection(targets=1, boots=1), Detection(targets=2)):
            self.assertEqual(session.observe(detection), "multiple")
        self.assertEqual(session.state, "waiting")

    def test_mixed_old_and_new_app_boards_are_rejected(self):
        session = self.make_session(True, target_pid=0x1234)
        self.assertEqual(session.observe(Detection(apps=1, targets=1)), "multiple")

    def test_pausing_factory_prevents_new_attempt(self):
        session = self.make_session(True)
        session.paused = True
        self.assertEqual(session.observe(Detection(apps=1)), "paused")
        session.paused = False
        self.assertEqual(session.observe(Detection(apps=1)), "start")
        self.assertEqual(session.observe(Detection(apps=1)), "idle")

    def test_direct_boot_is_available_by_default_and_for_legacy_false_setting(self):
        session = self.make_session(True)
        self.assertEqual(session.observe(Detection(boots=1)), "start")
        session = self.make_session(True, allow_boot_recovery=False)
        self.assertEqual(session.observe(Detection(boots=1)), "start")

    def test_modes_roundtrip_and_legacy_packages_default_to_single(self):
        for mode in ("single", "continuous"):
            package = Package(replace(Settings(), burn_mode=mode), image())
            self.assertEqual(decode_package(encode_package(package)).settings.burn_mode, mode)
        original = zipfile.ZipFile(io.BytesIO(encode_package(Package(Settings(), image()))))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as out:
            for name in original.namelist():
                data = original.read(name)
                if name == "manifest.json":
                    manifest = json.loads(data.decode())
                    del manifest["settings"]["burn_mode"]
                    manifest["settings"]["auto_start"] = False
                    data = json.dumps(manifest).encode()
                out.writestr(name, data)
        self.assertEqual(decode_package(stream.getvalue()).settings.burn_mode, "single")

    def test_manual_single_requires_activation_and_rearms_manually_after_error(self):
        session = self.make_session(auto_start=False)
        for _ in range(10):
            self.assertEqual(session.observe(Detection(apps=1, targets=1)), "ready")
            self.assertFalse(session.begin())
        self.assertTrue(session.activate())
        self.assertEqual(session.observe(Detection(apps=1, targets=1)), "start")
        self.assertTrue(session.begin())
        session.complete(error="failed")
        session.observe(Detection())
        self.clock.sleep(.7)
        self.assertEqual(session.observe(Detection()), "next")
        self.assertEqual(session.observe(Detection(apps=1, targets=1)), "ready")

    def test_manual_factory_click_starts_station_and_next_boards_are_automatic(self):
        session = self.make_session(True, auto_start=False)
        self.assertEqual(session.observe(Detection(apps=1)), "ready")
        self.assertTrue(session.activate())
        self.successful_attempt(session)
        session.observe(Detection())
        self.clock.sleep(.7)
        self.assertEqual(session.observe(Detection()), "next")
        self.assertEqual(session.observe(Detection(apps=1)), "start")


if __name__ == "__main__":
    unittest.main()
