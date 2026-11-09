"""Read-only smoke checks against a frozen executable. Never upgrades USB."""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--output", default="build/smoke")
    args = parser.parse_args()
    exe = str(Path(args.executable).resolve())
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    diagnostics = output / "diagnostics.json"
    screenshot = output / "window.png"
    options = {}
    if sys.platform == "win32":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        options["startupinfo"] = startup
    subprocess.run([exe, "--diagnostics", str(diagnostics)], check=True, timeout=60, **options)
    result = json.loads(diagnostics.read_text(encoding="utf-8"))
    assert result["libusb_available"] is True
    assert isinstance(result["hid_interfaces"], list)
    subprocess.run([exe, "--preview", "--screenshot", str(screenshot)], check=True, timeout=60, **options)
    assert screenshot.exists() and screenshot.stat().st_size > 1000
    print("Frozen executable: HID/libusb loaded and safe preview rendered.")
    print(str(output))


if __name__ == "__main__":
    main()
