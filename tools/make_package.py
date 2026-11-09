"""Noninteractive packager. Writes files only; never opens a USB device."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qmk_updater.firmware import load_firmware
from qmk_updater.package import Settings, Package, encode_package, create_executable, create_mac_app
from qmk_updater.runtimes import system_package, validate_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--firmware", required=True)
    parser.add_argument("--settings", help="JSON settings, or a saved maker project")
    parser.add_argument("--template", help="Native executable or .app; omit for a portable .qmk")
    parser.add_argument("--runtime", help="Prebuilt .qmk-runtime.zip; assembles for its OS on any host")
    parser.add_argument("--background", default=None, help="Customer background, e.g. #FFFFFF or #11151C")
    parser.add_argument("--output", required=True)
    parser.add_argument("--base", default="08000000")
    parser.add_argument("--mode", choices=("single", "continuous"), help="Single customer or continuous factory package")
    startup = parser.add_mutually_exclusive_group()
    startup.add_argument("--auto-start", dest="auto_start", action="store_true", help="Start on device detection")
    startup.add_argument("--manual-start", dest="auto_start", action="store_false", help="Require the customer to click Start")
    parser.set_defaults(auto_start=None)
    args = parser.parse_args()
    firmware = load_firmware(args.firmware, int(args.base, 16))
    if args.settings:
        content = json.loads(Path(args.settings).read_text(encoding="utf-8"))
        settings = Settings(**content.get("settings", content))
    else:
        usbs, hids = firmware.usb_candidates(), firmware.hid_candidates()
        if len(usbs) != 1 or len(hids) != 1:
            parser.error("Ambiguous descriptors; provide explicit --settings")
        u, h = usbs[0], hids[0]
        strings = firmware.strings()
        settings = Settings(product=strings[-1] if strings else Path(args.firmware).stem,
                            version="%X.%X.%X" % (u.version >> 8, (u.version >> 4) & 15, u.version & 15),
                            app_vid=u.vid, app_pid=u.pid, usage_page=h.usage_page, usage_id=h.usage,
                            report_size=h.report_size, report_id=h.report_id,
                            target_vid=u.vid, target_pid=u.pid, target_usage_page=h.usage_page, target_usage_id=h.usage)
    if args.auto_start is not None:
        settings.auto_start = args.auto_start
    if args.mode:
        settings.burn_mode = args.mode
    if args.background:
        settings.background = args.background
    data = encode_package(Package(settings, firmware))
    if args.runtime:
        if args.template:
            parser.error("Choose --runtime or --template")
        target = validate_runtime(args.runtime)["target"]
        system_package(args.runtime, args.output, data, target)
    elif args.template:
        if Path(args.template).suffix == ".app":
            create_mac_app(args.template, args.output, data)
        else:
            create_executable(args.template, args.output, data)
    else:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_bytes(data)
    print("Created " + str(Path(args.output).resolve()))


if __name__ == "__main__":
    main()
