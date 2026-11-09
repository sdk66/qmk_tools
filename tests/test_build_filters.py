import unittest

from tools.build_filters import add_windows_filter, windows_widget_entries


def entry(name):
    return (name, "/wheel/" + name.replace("\\", "/"), "BINARY")


class WindowsBuildFilterTests(unittest.TestCase):
    def test_widget_build_keeps_platforms_drivers_usb_and_win7_runtime(self):
        keep = [entry(name) for name in (
            "PySide2/Qt5Core.dll", "PySide2/Qt5Gui.dll", "PySide2/Qt5Widgets.dll",
            "PySide2/plugins/platforms/qwindows.dll", "PySide2/plugins/platforms/qoffscreen.dll",
            "PySide2/plugins/imageformats/qico.dll", "PySide2/plugins/imageformats/qjpeg.dll",
            "libusb-1.0.dll", "libusb_package/libusb-1.0.dll", "hid.pyd",
            "ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll", "VCRUNTIME140.dll",
        )]
        remove = [entry(name) for name in (
            "PySide2/Qt5Pdf.dll", "PySide2/Qt5Quick.dll", "PySide2/Qt5Qml.dll",
            "PySide2/Qt5QmlModels.dll", "PySide2/Qt5VirtualKeyboard.dll", "PySide2/Qt5WebSockets.dll",
            "PySide2/plugins/imageformats/qpdf.dll", "PySide2/plugins/platforms/qwebgl.dll",
            "PySide2/plugins/platforms/qdirect2d.dll", "PySide2/plugins/platforms/qminimal.dll",
            "PySide2/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
            "PySide2/opengl32sw.dll", "PySide2/d3dcompiler_47.dll",
            "PySide2/libGLESv2.dll", "PySide2/libEGL.dll",
        )]
        resources = [entry(name) for name in (
            "icon.png", "drivers/windows/WB32-WinUSB-official.zip",
            "licenses/PySide2/LICENSE.LGPLv3", "THIRD_PARTY_NOTICES.md",
        )]
        actual, datas = windows_widget_entries(keep + remove, resources, imports=lambda _: set())
        self.assertEqual(actual, keep)
        self.assertEqual(datas, resources)

    def test_retains_normal_and_delay_import_dependency_closure(self):
        binaries = [entry(name) for name in (
            "PySide2/Qt5Gui.dll", "PySide2/libEGL.dll", "PySide2/libGLESv2.dll",
            "PySide2/d3dcompiler_47.dll", "PySide2/opengl32sw.dll",
        )]
        dependencies = {
            binaries[0][1]: {"libEGL.dll"},
            binaries[1][1]: {"LIBGLESV2.DLL"},
            binaries[2][1]: {"d3dcompiler_47.dll"},
        }
        actual, _ = windows_widget_entries(binaries, [], imports=lambda p: dependencies.get(p, set()))
        self.assertEqual(actual, binaries[:-1])

    def test_filters_only_qt_owned_components_and_translations(self):
        keep = [entry("other/libEGL.dll"), entry("other/qpdf.dll")]
        qt = [entry(r"PySide2\libEGL.dll"), entry(r"PySide2\plugins\imageformats\qpdf.dll")]
        keep_data = [entry("licenses/PySide2/translation-notice.txt"), entry("translations/application.qm")]
        actual, data = windows_widget_entries(keep + qt,
            keep_data + [entry(r"PySide2\translations\qt_zh_CN.qm")], imports=lambda _: set())
        self.assertEqual(actual, keep)
        self.assertEqual(data, keep_data)

    def test_spec_filter_executes_before_executable_collection(self):
        source = "a = Analysis([])\npyz = PYZ(a.pure)\nexe = EXE(pyz, a.binaries)\n"
        output = add_windows_filter(source, ".")
        self.assertLess(output.index("filter_windows_analysis(a)"), output.index("pyz = PYZ("))
        with self.assertRaises(RuntimeError):
            add_windows_filter("unexpected spec structure", ".")


if __name__ == "__main__":
    unittest.main()
