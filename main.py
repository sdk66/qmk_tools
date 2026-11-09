"""Run the maker; a generated executable automatically opens the updater."""
import argparse
import json
import os
import sys
import traceback
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="QMK Firmware Studio / WB32FQ95")
    parser.add_argument("--firmware", help="Preload a HEX/BIN in the maker; never sends USB commands")
    parser.add_argument("--package", help="Open a portable .qmk package")
    parser.add_argument("--preview", action="store_true", help="Show the customer UI with all device I/O disabled")
    parser.add_argument("--screenshot", help="Capture the window and exit; disables all device I/O")
    parser.add_argument("--inspect", help="Print validated package metadata and exit; no Qt or USB")
    parser.add_argument("--diagnostics", help="Write read-only HID/libusb diagnostics to a JSON file and exit")
    args = parser.parse_args()
    from qmk_updater.package import embedded_package, decode_package
    if args.diagnostics:
        import hid
        from qmk_updater.devices import usb_backend, Hardware
        from qmk_updater.package import Settings
        result = {"python": sys.version, "platform": sys.platform,
                  "libusb_available": usb_backend() is not None,
                  "hid_interfaces": [{key: d.get(key) for key in
                                      ("vendor_id", "product_id", "usage_page", "usage", "interface_number")}
                                     for d in hid.enumerate()],
                  "wb32_boot_count": len(Hardware().boot_devices(Settings()))}
        Path(args.diagnostics).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0
    if args.inspect:
        from dataclasses import asdict
        from qmk_updater.package import read_overlay
        path = Path(args.inspect)
        data = read_overlay(path) if path.suffix.lower() != ".qmk" else path.read_bytes()
        if data is None:
            raise ValueError("No embedded package")
        p = decode_package(data)
        print(json.dumps({"settings": asdict(p.settings), "firmware": p.firmware.name,
                          "size": p.firmware.size, "segments": len(p.firmware.segments)}, ensure_ascii=True, indent=2))
        return 0
    from qmk_updater.qt import QApplication, QTimer, Qt
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("QMK Firmware Studio")
    app.setOrganizationName("QMK-Firmware-Studio")
    from qmk_updater.ui import MakerWindow
    from qmk_updater.updater_window import UpdaterWindow
    try:
        package = embedded_package()
        # Embedded packages are immutable from the customer's command line.
        if package is None and args.package:
            package = decode_package(Path(args.package).read_bytes())
        if package:
            window = UpdaterWindow(package, safe_preview=bool(args.preview or args.screenshot))
        else:
            window = MakerWindow()
            if args.firmware:
                window.load_firmware(args.firmware)
    except Exception as e:
        from qmk_updater.qt import QMessageBox
        QMessageBox.critical(None, "升级包无法打开", str(e))
        return 1
    window.show()
    if args.screenshot:
        def capture():
            window.grab().save(str(Path(args.screenshot).resolve()))
            app.quit()
        QTimer.singleShot(900, capture)
    return app.exec_() if hasattr(app, "exec_") else app.exec()


if __name__ == "__main__":
    sys.exit(main())
