"""Windows file properties must agree with the named release executable."""
import unittest

from tools.windows_version import windows_version_resource


class WindowsVersionTests(unittest.TestCase):
    def parse_resource(self, source):
        # PyInstaller uses these constructor names when loading a version file.
        # Collect their arguments without importing Windows-only dependencies.
        captured = {}

        def fixed(**kwargs):
            captured["fixed"] = kwargs
            return kwargs

        def string(key, value):
            captured.setdefault("strings", {})[key] = value
            return key, value

        context = {name: lambda *args, **kwargs: (args, kwargs) for name in (
            "VSVersionInfo", "StringFileInfo", "StringTable", "VarFileInfo", "VarStruct")}
        context.update(FixedFileInfo=fixed, StringStruct=string)
        eval(compile(source, "<windows-version>", "eval"), {"__builtins__": {}}, context)
        return captured

    def test_actual_release_version_matches_windows_properties_and_filename(self):
        filename = "QMK_Firmware_Toolbox_Package_1.6.0.exe"
        parsed = self.parse_resource(windows_version_resource("1.6.0", filename))
        self.assertEqual(parsed["fixed"]["filevers"], (1, 6, 0, 0))
        self.assertEqual(parsed["fixed"]["prodvers"], (1, 6, 0, 0))
        self.assertEqual(parsed["strings"]["FileVersion"], "1.6.0")
        self.assertEqual(parsed["strings"]["ProductVersion"], "1.6.0")
        self.assertEqual(parsed["strings"]["OriginalFilename"], filename)
        self.assertEqual(parsed["strings"]["ProductName"], "QMK Firmware Toolbox Package")

    def test_new_release_version_is_not_hardcoded(self):
        parsed = self.parse_resource(windows_version_resource(
            "2.17.31", "QMK_Firmware_Toolbox_Package_2.17.31.exe"))
        self.assertEqual(parsed["fixed"]["filevers"], (2, 17, 31, 0))
        self.assertEqual(parsed["strings"]["ProductVersion"], "2.17.31")

    def test_invalid_numeric_versions_and_non_basenames_are_rejected(self):
        for version in ("", "1.6", "1.6.0.1", "1.6.0-rc1", "-1.6.0", "65536.0.0"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                windows_version_resource(version, "tool.exe")
        for filename in ("", ".exe", "tool.zip", "../tool.exe", "C:\\tool.exe", "bad\x00.exe"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                windows_version_resource("1.6.0", filename)


if __name__ == "__main__":
    unittest.main()
