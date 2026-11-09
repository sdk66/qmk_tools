"""Maker directory history and packaging responsiveness, without real USB I/O."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qmk_updater.qt import QApplication, QTimer
from qmk_updater.preferences import MakerPreferences
from qmk_updater.ui import MakerWindow


ROOT = Path(__file__).resolve().parent.parent


class MakerPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.preferences_path = self.root / "settings" / "preferences.json"
        self.firmware_directory = self.root / "firmware"
        self.output_directory = self.root / "customer packages"
        self.other_firmware_directory = self.root / "other firmware"
        for directory in (self.firmware_directory, self.output_directory, self.other_firmware_directory):
            directory.mkdir()
        self.source = self.firmware_directory / "board_v9.hex"
        self.other_source = self.other_firmware_directory / "board_v10.hex"
        firmware = (ROOT / "mk20b_via_v9.hex").read_bytes()
        self.source.write_bytes(firmware)
        self.other_source.write_bytes(firmware)
        self.template_path = self.root / "unused-template.exe"
        self.windows = []
        self.hardware_patch = patch("qmk_updater.ui.Hardware", side_effect=AssertionError("Real USB is forbidden in maker tests"))
        self.template_patch = patch.object(MakerWindow, "template", return_value=self.template_path)
        self.information_patch = patch("qmk_updater.ui.QMessageBox.information")
        self.warning_patch = patch("qmk_updater.ui.QMessageBox.warning")
        self.question_patch = patch("qmk_updater.ui.QMessageBox.question", side_effect=AssertionError("Fixture descriptors must be detected"))
        for mocked in (self.hardware_patch, self.template_patch, self.information_patch,
                       self.warning_patch, self.question_patch):
            self.addCleanup(mocked.stop)
        self.hardware_patch.start()
        self.template_patch.start()
        self.information = self.information_patch.start()
        self.warning = self.warning_patch.start()
        self.question_patch.start()

    def tearDown(self):
        for window in self.windows:
            self.assertIsNone(window.pack_worker, "Packaging must finish before leaving its mock context")
            window.close()
            window.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def wait_until(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Qt event loop did not reach the expected packaging state")

    def new_window(self, load=False):
        preferences = MakerPreferences(path=self.preferences_path, fallback_directory=self.root)
        window = MakerWindow(preferences=preferences)
        self.windows.append(window)
        window.platform_combo.setCurrentIndex(window.platform_combo.findData("windows-x64"))
        if load:
            window.load_firmware(self.source)
        window.show()
        self.app.processEvents()
        return window

    def save_immediate_package(self, window, destination):
        def build(template, path, data, target, progress=None):
            Path(path).write_bytes(b"mock customer updater")
            progress(100, "测试打包完成")

        with patch("qmk_updater.ui.QFileDialog.getSaveFileName", return_value=(str(destination), "")) as save, \
                patch("qmk_updater.packaging_job.system_package", side_effect=build) as package:
            try:
                window.generate_package()
            finally:
                self.wait_until(lambda: window.pack_worker is None)
        package.assert_called_once()
        return save.call_args

    def test_firmware_and_output_dialogs_remember_independent_directories_across_windows(self):
        first = self.new_window()
        with patch("qmk_updater.ui.QFileDialog.getOpenFileName", return_value=(str(self.source), "")) as select:
            first.select_firmware()
        self.assertEqual(select.call_args.args[2], str(self.root))
        self.assertEqual(first.firmware_path, self.source.resolve())
        self.assertEqual(first.preferences.directory("output"), str(self.root))
        destination = self.output_directory / "board_v9_update.exe"
        saved = self.save_immediate_package(first, destination)
        self.assertEqual(Path(saved.args[2]), self.root / "board_v9_update.exe")
        self.assertTrue(destination.is_file())
        self.assertFalse(self.warning.called)

        second = self.new_window()
        with patch("qmk_updater.ui.QFileDialog.getOpenFileName", return_value=(str(self.other_source), "")) as select:
            second.select_firmware()
        self.assertEqual(select.call_args.args[2], str(self.firmware_directory))
        with patch("qmk_updater.ui.QFileDialog.getSaveFileName", return_value=("", "")) as save:
            second.generate_package()
        self.assertEqual(Path(save.call_args.args[2]), self.output_directory / "board_v10_update.exe")
        self.assertIsNone(second.pack_worker)

        third = self.new_window()
        self.assertEqual(third.preferences.directory("firmware"), str(self.other_firmware_directory))
        self.assertEqual(third.preferences.directory("output"), str(self.output_directory))

    def test_cancelling_either_dialog_does_not_change_saved_directories(self):
        preferences = MakerPreferences(path=self.preferences_path, fallback_directory=self.root)
        preferences.remember_file("firmware", self.source)
        preferences.remember_file("output", self.output_directory / "previous_update.exe")
        before = self.preferences_path.read_bytes()
        window = self.new_window(load=True)
        with patch("qmk_updater.ui.QFileDialog.getOpenFileName", return_value=("", "")) as select:
            window.select_firmware()
        self.assertEqual(select.call_args.args[2], str(self.firmware_directory))
        self.assertEqual(window.firmware_path, self.source.resolve())
        with patch("qmk_updater.ui.QFileDialog.getSaveFileName", return_value=("", "")) as save, \
                patch("qmk_updater.packaging_job.system_package") as package:
            window.generate_package()
        self.assertEqual(Path(save.call_args.args[2]), self.output_directory / "board_v9_update.exe")
        package.assert_not_called()
        self.assertIsNone(window.pack_worker)
        self.assertEqual(self.preferences_path.read_bytes(), before)
        reopened = self.new_window()
        self.assertEqual(reopened.preferences.directory("firmware"), str(self.firmware_directory))
        self.assertEqual(reopened.preferences.directory("output"), str(self.output_directory))

    def run_gated_package(self, error=None):
        window = self.new_window(load=True)
        original_states = {widget: widget.isEnabled() for widget in (
            window.generate, window.inputs["product"], window.platform_combo,
            window.auto_start, window.single_mode, window.continuous_mode,
            window.base, window.apply_base)}
        entered, release = threading.Event(), threading.Event()
        worker_threads = []
        destination = self.output_directory / "board_v9_update.exe"

        def build(template, path, data, target, progress=None):
            worker_threads.append(threading.get_ident())
            progress(35, "测试后台打包进行中")
            entered.set()
            if not release.wait(4):
                raise AssertionError("Test did not release the packaging gate")
            if error is not None:
                raise error
            Path(path).write_bytes(b"mock customer updater")
            progress(100, "测试打包完成")

        with patch("qmk_updater.ui.QFileDialog.getSaveFileName", return_value=(str(destination), "")) as save, \
                patch("qmk_updater.packaging_job.system_package", side_effect=build) as package:
            try:
                window.generate_package()
                self.wait_until(lambda: entered.is_set() and "35%" in window.generate.text())
                worker = window.pack_worker
                self.assertIsNotNone(worker)
                self.assertTrue(worker.isRunning())
                self.assertTrue(window._pack_controls)
                self.assertTrue(all(not widget.isEnabled() for widget, enabled in window._pack_controls))
                self.assertEqual(window.status.text(), "测试后台打包进行中")

                # A queued UI callback must run while package construction is blocked.
                callbacks = []
                QTimer.singleShot(0, lambda: callbacks.append("responsive"))
                self.wait_until(lambda: callbacks)
                self.assertEqual(callbacks, ["responsive"])
                self.assertNotEqual(worker_threads, [threading.get_ident()])
                self.assertFalse(window.close())
                self.assertTrue(window.isVisible())
                self.assertIn("等待完成后关闭", window.status.text())
                window.generate_package()
                self.assertEqual(save.call_count, 1)
                package.assert_called_once()
            finally:
                release.set()
                # finished is queued to the GUI; wait for its handler before
                # removing the mocked builder or deleting any Qt objects.
                self.wait_until(lambda: window.pack_worker is None)

        self.assertEqual(window.generate.text(), "生成升级程序")
        for widget, enabled in original_states.items():
            self.assertEqual(widget.isEnabled(), enabled)
        self.assertEqual(window._pack_controls, [])
        self.assertTrue(window.close())
        return window, destination

    def test_background_packaging_keeps_ui_responsive_and_restores_controls_on_success(self):
        window, destination = self.run_gated_package()
        self.assertTrue(destination.is_file())
        self.assertIn("已生成", window.status.text())
        self.information.assert_called_once()
        self.assertEqual(self.information.call_args.args[1], "升级包制作完成")
        self.assertIn(str(destination), self.information.call_args.args[2])
        self.assertIn("5 秒", self.information.call_args.args[2])
        self.warning.assert_not_called()

    def test_background_packaging_restores_controls_and_reports_build_failure(self):
        window, destination = self.run_gated_package(error=OSError("测试输出目录不可写"))
        self.assertFalse(destination.exists())
        self.assertEqual(window.status.text(), "打包失败：测试输出目录不可写")
        self.warning.assert_called_once()
        self.assertEqual(self.warning.call_args.args[1:], ("升级包未生成", "测试输出目录不可写"))
        self.information.assert_not_called()


if __name__ == "__main__":
    unittest.main()
