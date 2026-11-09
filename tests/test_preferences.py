import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from qmk_updater.preferences import MakerPreferences, default_preferences_path


class MakerPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = self.root / "settings" / "preferences.json"
        self.firmware = self.root / "firmware"
        self.output = self.root / "customer packages"
        self.firmware.mkdir()
        self.output.mkdir()

    def preferences(self, **kwargs):
        return MakerPreferences(path=self.settings, fallback_directory=self.root, **kwargs)

    def write_settings(self, data):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps(data), encoding="utf-8")

    def test_missing_preferences_use_fallback_without_creating_files(self):
        preferences = self.preferences()
        self.assertEqual(preferences.directory("firmware"), str(self.root))
        self.assertEqual(preferences.directory("output"), str(self.root))
        self.assertFalse(self.settings.parent.exists())

    def test_firmware_and_output_locations_survive_separately_across_launches(self):
        preferences = self.preferences()
        self.assertTrue(preferences.remember_file("firmware", self.firmware / "keyboard.hex"))
        self.assertTrue(preferences.remember_file("output", self.output / "keyboard_update.exe"))

        reopened = self.preferences()
        self.assertEqual(reopened.directory("firmware"), str(self.firmware))
        self.assertEqual(reopened.directory("output"), str(self.output))
        self.assertTrue(reopened.remember_file("firmware", self.root / "other.bin"))
        reopened_again = self.preferences()
        self.assertEqual(reopened_again.directory("firmware"), str(self.root))
        self.assertEqual(reopened_again.directory("output"), str(self.output))

    def test_unselected_output_does_not_follow_firmware_input(self):
        preferences = self.preferences()
        preferences.remember_file("firmware", self.firmware / "keyboard.hex")
        self.assertEqual(preferences.directory("output"), str(self.root))

    def test_cancelled_selection_does_not_create_or_change_preferences(self):
        preferences = self.preferences()
        for path in (None, "", "   "):
            self.assertFalse(preferences.remember_file("firmware", path))
        self.assertFalse(self.settings.parent.exists())
        preferences.remember_file("firmware", self.firmware / "keyboard.hex")
        before = self.settings.read_bytes()
        self.assertFalse(preferences.remember_file("firmware", ""))
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(preferences.directory("firmware"), str(self.firmware))

    def test_removed_saved_directory_uses_nearest_existing_parent(self):
        preferences = self.preferences()
        preferences.remember_file("output", self.output / "removed" / "nested" / "update.exe")
        self.assertEqual(self.preferences().directory("output"), str(self.output))

    def test_saved_path_that_is_now_a_file_uses_its_parent(self):
        stale_directory = self.output / "replaced-folder"
        preferences = self.preferences()
        preferences.remember_file("output", stale_directory / "update.exe")
        stale_directory.write_text("now a file", encoding="utf-8")
        self.assertEqual(self.preferences().directory("output"), str(self.output))

    def test_corrupted_or_invalid_json_is_ignored_and_can_be_replaced(self):
        self.settings.parent.mkdir(parents=True)
        for content in ("{bad json", "[]", "null", '{"directories": []}', "\xff"):
            with self.subTest(content=content):
                self.settings.write_bytes(content.encode("latin-1"))
                preferences = self.preferences()
                self.assertEqual(preferences.directory("firmware"), str(self.root))
                self.assertTrue(preferences.remember_file("firmware", self.firmware / "k.hex"))
                self.assertEqual(self.preferences().directory("firmware"), str(self.firmware))

    def test_invalid_values_and_unrelated_settings_are_not_used_or_saved(self):
        self.write_settings({
            "customer": {"theme": "blue"},
            "directories": {"firmware": 42, "output": "relative/path", "customer": str(self.output)},
        })
        preferences = self.preferences()
        self.assertEqual(preferences.directory("firmware"), str(self.root))
        self.assertEqual(preferences.directory("output"), str(self.root))
        preferences.remember_file("firmware", self.firmware / "keyboard.hex")
        saved = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"version": 1, "directories": {"firmware": str(self.firmware)}})

    def test_unicode_and_pathlike_files_are_saved(self):
        directory = self.root / "\u56fa\u4ef6\u5347\u7ea7"
        directory.mkdir()
        preferences = self.preferences()
        self.assertTrue(preferences.remember_file("firmware", directory / "\u952e\u76d8.bin"))
        self.assertEqual(self.preferences().directory("firmware"), str(directory))

    def test_failed_atomic_replace_preserves_previous_settings_and_cleans_temporary_file(self):
        preferences = self.preferences()
        preferences.remember_file("firmware", self.firmware / "keyboard.hex")
        before = self.settings.read_bytes()
        with mock.patch("qmk_updater.preferences.os.replace", side_effect=PermissionError("busy")):
            self.assertFalse(preferences.remember_file("output", self.output / "update.exe"))
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(list(self.settings.parent.glob(".preferences-*.tmp")), [])
        self.assertEqual(preferences.directory("output"), str(self.output))
        self.assertEqual(self.preferences().directory("output"), str(self.root))

    def test_unwritable_settings_location_does_not_break_current_session(self):
        preferences = self.preferences()
        with mock.patch("qmk_updater.preferences.Path.mkdir", side_effect=PermissionError("denied")):
            self.assertFalse(preferences.remember_file("firmware", self.firmware / "keyboard.hex"))
        self.assertEqual(preferences.directory("firmware"), str(self.firmware))

    def test_unreadable_settings_location_is_safe(self):
        self.settings.mkdir(parents=True)
        self.assertEqual(self.preferences().directory("firmware"), str(self.root))

    def test_optional_kinds_remain_independent_and_unknown_kinds_fail_early(self):
        preferences = self.preferences()
        preferences.remember_file("template", self.firmware / "template.qmk-runtime.zip")
        preferences.remember_file("project", self.output / "project.json")
        reopened = self.preferences()
        self.assertEqual(reopened.directory("template"), str(self.firmware))
        self.assertEqual(reopened.directory("project"), str(self.output))
        self.assertEqual(reopened.directory("output"), str(self.root))
        with self.assertRaises(ValueError):
            reopened.directory("customer")
        with self.assertRaises(ValueError):
            reopened.remember_file("customer", self.output / "update.exe")

    def test_default_directory_prefers_documents_then_home(self):
        with mock.patch("qmk_updater.preferences.Path.home", return_value=self.root):
            preferences = MakerPreferences(path=self.settings)
            self.assertEqual(preferences.directory("firmware"), str(self.root))
            documents = self.root / "Documents"
            documents.mkdir()
            self.assertEqual(preferences.directory("firmware"), str(documents))

    def test_environment_override_is_used_without_writing_during_construction(self):
        with mock.patch.dict(os.environ, {"QMK_PREFERENCES_PATH": str(self.settings)}):
            self.assertEqual(default_preferences_path(), self.settings)
            preferences = MakerPreferences(fallback_directory=self.root)
            self.assertEqual(preferences.path, self.settings)
        self.assertFalse(self.settings.exists())

    def test_default_settings_path_matches_each_platform(self):
        cases = (
            ("win32", {"LOCALAPPDATA": str(self.root / "local")}, self.root / "local"),
            ("win32", {}, self.root / "AppData" / "Local"),
            ("darwin", {}, self.root / "Library" / "Application Support"),
            ("linux", {"XDG_CONFIG_HOME": str(self.root / "xdg")}, self.root / "xdg"),
            ("linux", {}, self.root / ".config"),
        )
        for platform, environment, base in cases:
            with self.subTest(platform=platform, environment=environment):
                with mock.patch.dict(os.environ, environment, clear=True), \
                        mock.patch("qmk_updater.preferences.sys.platform", platform), \
                        mock.patch("qmk_updater.preferences.Path.home", return_value=self.root):
                    expected = base / "QMK-Firmware-Studio" / "preferences.json"
                    self.assertEqual(default_preferences_path(), expected)
        self.assertFalse(self.settings.exists())


if __name__ == "__main__":
    unittest.main()
