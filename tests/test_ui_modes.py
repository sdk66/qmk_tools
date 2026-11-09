"""Qt lifecycle checks with all discovery/USB strictly mocked."""
import os
import time
import tempfile
import zipfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qmk_updater.qt import QApplication
from qmk_updater.ui import MakerWindow
from qmk_updater.updater_window import UpdaterWindow
from qmk_updater.package import Settings, Package, encode_package, decode_package
from qmk_updater.session import Detection
from qmk_updater.workflow import Outcome
from test_core import FakeClock, FakeHardware, FakeTransport, image


class StationHardware(FakeHardware):
    def __init__(self):
        super().__init__()
        self.connected = True

    def app_devices(self, settings, target=False):
        if not self.connected:
            return []
        if self.transport.reset_called:
            return [{"path": b"app", "product_string": "Test Keyboard"}]
        return super().app_devices(settings, target)

    def boot_devices(self, settings):
        return super().boot_devices(settings) if self.connected else []


class UiModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.windows = []
        self.hardware_patch = patch("qmk_updater.ui.Hardware", side_effect=AssertionError("Real USB is forbidden in UI tests"))
        self.hardware_patch.start()

    def tearDown(self):
        for window in self.windows:
            if hasattr(window, "timer"):
                window.timer.stop()
                window.countdown_timer.stop()
                for thread in (window.probe, window.worker):
                    if thread and thread.isRunning():
                        thread.wait(5000)
                window.busy = False
                window.worker = None
            window.close()
            window.deleteLater()
        self.app.processEvents()
        self.hardware_patch.stop()

    def updater(self, continuous=False, auto_start=True):
        window = UpdaterWindow(Package(replace(Settings(), burn_mode="continuous" if continuous else "single", auto_start=auto_start), image()), safe_preview=True)
        self.windows.append(window)
        window.show()
        self.app.processEvents()
        return window

    def test_maker_packs_modes_and_auto_start_checkbox(self):
        window = MakerWindow()
        self.windows.append(window)
        window.load_firmware(Path(__file__).resolve().parent.parent / "mk20b_via_v9.hex")
        self.assertEqual(window.settings().burn_mode, "single")
        self.assertTrue(window.settings().auto_start)
        self.assertEqual(window.usb_version.text(), "0x0200")
        self.assertIn("5 秒", window.mode_hint.text())
        window.auto_start.setChecked(False)
        self.assertFalse(window.settings().auto_start)
        window.continuous_mode.setChecked(True)
        self.assertEqual(window.settings().burn_mode, "continuous")
        self.assertIn("下一把", window.mode_hint.text())
        result = decode_package(encode_package(Package(window.settings(), window.firmware)))
        self.assertEqual(result.settings.burn_mode, "continuous")
        self.assertFalse(result.settings.auto_start)

    def test_percentage_progress_is_visible_and_logs_can_be_expanded(self):
        window = self.updater()
        self.assertFalse(window.log.isVisible())
        window.log_toggle.click()
        self.assertTrue(window.log.isVisible())
        self.assertTrue(window.progress_bar.isTextVisible())
        window.update_progress(47, "writing page")
        self.assertEqual(window.progress_bar.value(), 47)
        self.assertEqual(window.message.text(), "writing page")

    def test_customer_background_is_packed_and_preview_does_not_recolor_maker(self):
        window = MakerWindow()
        self.windows.append(window)
        window.load_firmware(Path(__file__).resolve().parent.parent / "mk20b_via_v9.hex")
        maker_style = window.styleSheet()
        self.assertEqual(window.settings().background, "#FFFFFF")
        self.assertNotIn("本机", " ".join(window.platform_combo.itemText(i) for i in range(window.platform_combo.count())))
        window.background_combo.setCurrentIndex(window.background_combo.findData("#11151C"))
        result = decode_package(encode_package(Package(window.settings(), window.firmware)))
        self.assertEqual(result.settings.background, "#11151C")
        self.assertEqual(window.styleSheet(), maker_style)
        self.assertIn("#11151C", window.customer_preview.styleSheet())

    def test_maker_generates_selected_mac_package_using_imported_runtime(self):
        from qmk_updater.runtimes import create_runtime_archive, PAYLOAD_NAME
        from test_runtimes import binary_header
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "Native.app"
            executable = app / "Contents" / "MacOS" / "QMK-Firmware-Studio"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(binary_header("macos-arm64"))
            create_runtime_archive(app, root / "macos-arm64.qmk-runtime.zip", "macos-arm64")
            window = MakerWindow()
            self.windows.append(window)
            window.load_firmware(Path(__file__).resolve().parent.parent / "mk20b_via_v9.hex")
            destination = root / "keyboard.zip"
            with patch("qmk_updater.ui.templates_directory", return_value=root), \
                 patch("qmk_updater.ui.QFileDialog.getSaveFileName", return_value=(str(destination), "")), \
                 patch("qmk_updater.ui.QMessageBox.information"), \
                 patch("qmk_updater.ui.QMessageBox.warning") as warning, \
                 patch("subprocess.run", side_effect=AssertionError("No host-specific commands allowed")):
                window.platform_combo.setCurrentIndex(window.platform_combo.findData("macos-arm64"))
                window.generate_package()
                warning.assert_not_called()
            with zipfile.ZipFile(destination) as archive:
                settings = decode_package(archive.read("keyboard/" + PAYLOAD_NAME)).settings
                self.assertEqual(settings.background, "#FFFFFF")
                self.assertIn("keyboard/keyboard.app/Contents/MacOS/QMK-Firmware-Studio", archive.namelist())

    def test_single_success_updates_countdown_and_closes_at_five_seconds(self):
        window = self.updater()
        clock = FakeClock()
        window.session.clock = clock.clock
        window.show_outcome(Outcome(True, "reconnected"))
        self.assertEqual(window.progress_bar.value(), 100)
        self.assertIn("5 秒", window.start_button.text())
        clock.sleep(4)
        window.countdown_tick()
        self.assertTrue(window.isVisible())
        self.assertIn("1 秒", window.start_button.text())
        clock.sleep(1)
        window.countdown_tick()
        self.assertFalse(window.isVisible())

    def test_factory_success_keeps_window_and_blocks_same_keyboard(self):
        window = self.updater(True)
        window.show_outcome(Outcome(True, "done"))
        window.consume_detection(Detection(apps=1, targets=1))
        self.assertTrue(window.isVisible())
        self.assertEqual(window.session.state, "remove")
        self.assertIn("下一把", window.message.text())
        self.assertIn("成功 1", window.counts.text())
        self.assertFalse(window.countdown_timer.isActive())

    def test_error_and_missing_reconnect_keep_window_and_never_count_down(self):
        for continuous in (False, True):
            window = self.updater(continuous)
            window.show_outcome(error="test write failure")
            self.assertTrue(window.isVisible())
            self.assertIsNone(window.session.remaining())
            window.show_outcome(Outcome(False, "not reconnected"))
            self.assertFalse(window.countdown_timer.isActive())
            self.assertIsNone(window.session.remaining())

    def test_safe_preview_cannot_start_real_discovery_or_upgrading(self):
        window = self.updater(True)
        window.probe_device()
        window.consume_detection(Detection(apps=1))
        window.start_upgrade()
        self.app.processEvents()
        self.assertIsNone(window.worker)
        self.assertIsNone(window.probe)
        self.assertFalse(window.timer.isActive())

    def wait_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate(), "Qt lifecycle did not reach the expected state")

    def test_single_threaded_discovery_automatically_flashes_without_button_click(self):
        hardware = StationHardware()
        with patch("qmk_updater.ui.Hardware", return_value=hardware):
            window = self.updater()
            window.safe_preview = False
            window.probe_device()
            self.wait_until(lambda: window.session.state == "countdown")
            self.assertEqual(hardware.jumps, 1)
            self.assertTrue(hardware.transport.reset_called)
            self.assertEqual(window.progress_bar.value(), 100)
            self.assertTrue(window.countdown_timer.isActive())

    def test_factory_processes_two_virtual_boards_and_never_repeats_connected_one(self):
        hardware = StationHardware()
        with patch("qmk_updater.ui.Hardware", return_value=hardware):
            window = self.updater(True)
            window.safe_preview = False
            window.probe_device()
            self.wait_until(lambda: window.session.succeeded == 1)
            until = time.monotonic() + 1.6
            self.wait_until(lambda: time.monotonic() >= until)
            self.assertEqual(hardware.jumps, 1)
            self.assertEqual(window.session.state, "remove")
            hardware.connected = False
            self.wait_until(lambda: window.session.state == "waiting")
            hardware.transport = FakeTransport()
            hardware.apps, hardware.boots, hardware.connected = 1, 0, True
            self.wait_until(lambda: window.session.succeeded == 2)
            self.assertEqual(hardware.jumps, 2)
            self.assertFalse(window.countdown_timer.isActive())
            self.assertTrue(window.isVisible())

    def test_manual_package_does_not_flash_connected_board_until_start_click(self):
        hardware = StationHardware()
        with patch("qmk_updater.ui.Hardware", return_value=hardware):
            window = self.updater(auto_start=False)
            window.safe_preview = False
            window.probe_device()
            self.wait_until(lambda: "等待开始" in window.message.text())
            self.assertEqual(hardware.jumps, 0)
            self.assertFalse(hardware.transport.commands)
            self.assertTrue(window.start_button.isEnabled())
            self.assertEqual(window.start_button.text(), "开始升级")
            window.start_button.click()
            self.wait_until(lambda: window.session.state == "countdown")
            self.assertEqual(hardware.jumps, 1)
            self.assertTrue(hardware.transport.reset_called)


if __name__ == "__main__":
    unittest.main()
