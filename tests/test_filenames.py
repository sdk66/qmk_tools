import unittest
from pathlib import PurePosixPath, PureWindowsPath

from qmk_updater.filenames import firmware_stem, package_filename


class FilenameTests(unittest.TestCase):
    def test_firmware_default_preserves_source_basename_and_adds_update(self):
        cases = (
            ("mk20b_via_v9.hex", "mk20b_via_v9_update"),
            (PureWindowsPath(r"C:\Firmware\键盘 v9.HEX"), "键盘 v9_update"),
            (PurePosixPath("/tmp/Keyboard release.BIN"), "Keyboard release_update"),
            ("/tmp/keyboard.release.hex", "keyboard.release_update"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(firmware_stem(source), expected)

    def test_default_does_not_depend_on_product_version_or_burn_mode(self):
        name = firmware_stem("mk20b_via_v9.hex")
        self.assertEqual(package_filename(name, ".exe"), "mk20b_via_v9_update.exe")
        self.assertEqual(package_filename(name, ".zip"), "mk20b_via_v9_update.zip")
        self.assertEqual(package_filename(name, ".tar.gz"), "mk20b_via_v9_update.tar.gz")

    def test_firmware_default_does_not_duplicate_existing_update_suffix(self):
        self.assertEqual(firmware_stem("keyboard_update.hex"), "keyboard_update")
        self.assertEqual(firmware_stem("keyboard_UPDATE.BIN"), "keyboard_UPDATE")

    def test_custom_name_does_not_require_update_suffix(self):
        self.assertEqual(package_filename("My keyboard", ".exe"), "My keyboard.exe")
        self.assertEqual(package_filename("My keyboard_update", ".zip"),
                         "My keyboard_update.zip")

    def test_edited_name_keeps_unicode_and_portably_replaces_invalid_characters(self):
        self.assertEqual(package_filename('客户<>:"/\\|?*\x00\x1f\x7f. ', ".exe"),
                         "客户" + "_" * 12 + ".exe")
        self.assertEqual(package_filename("  Final keyboard v2.  ", ".zip"),
                         "Final keyboard v2.zip")

    def test_existing_suffix_is_not_duplicated_and_changes_with_target(self):
        for existing in ("Keyboard.EXE", "Keyboard.ZIP", "Keyboard.TAR.GZ"):
            for extension in (".exe", ".zip", ".tar.gz"):
                with self.subTest(existing=existing, extension=extension):
                    output = package_filename(existing, extension)
                    self.assertEqual(output, "Keyboard" + extension)
                    self.assertEqual(package_filename(output, extension), output)

    def test_windows_device_names_are_safe_on_every_target(self):
        for name in ("CON", "prn", "AUX.release", "nul", "COM1", "LPT9", "COM¹", "CONIN$"):
            with self.subTest(name=name):
                self.assertEqual(package_filename(name, ".zip"), "_" + name + ".zip")
        self.assertEqual(package_filename("COM10", ".exe"), "COM10.exe")

    def test_empty_and_extension_only_names_use_safe_fallback(self):
        self.assertEqual(firmware_stem(".hex"), "firmware_update")
        self.assertEqual(package_filename("... ", ".exe"), "firmware.exe")
        self.assertEqual(package_filename(".ZIP", ".exe"), "firmware.exe")
        self.assertEqual(package_filename("", ".zip", fallback="客户版本"), "客户版本.zip")
        self.assertEqual(package_filename("", ".exe", fallback="NUL"), "_NUL.exe")
        self.assertEqual(package_filename("", ".exe", fallback=".."), "firmware.exe")

    def test_typed_paths_cannot_escape_the_output_directory(self):
        for name in ("../keyboard", r"..\keyboard", "/tmp/keyboard", r"C:\tmp\keyboard"):
            with self.subTest(name=name):
                output = package_filename(name, ".exe")
                self.assertNotIn("/", output)
                self.assertNotIn("\\", output)
                self.assertNotIn(":", output)
                self.assertFalse(output.startswith("."))

    def test_only_supported_target_extensions_are_allowed(self):
        self.assertEqual(package_filename("keyboard", ".EXE"), "keyboard.exe")
        with self.assertRaises(ValueError):
            package_filename("keyboard", "../bad")


if __name__ == "__main__":
    unittest.main()
