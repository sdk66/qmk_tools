"""Build a native maker, which also serves as its own customer template."""
import argparse
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    os.chdir(str(ROOT))
    assets = ROOT / "build" / "assets"
    licenses = assets / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    # Preserve all package license notices in the executable and release folder.
    for dist_name in ("PySide2", "shiboken2", "PySide6", "shiboken6", "hidapi", "pyusb", "libusb-package", "PyInstaller"):
        try:
            dist = importlib.metadata.distribution(dist_name)
        except importlib.metadata.PackageNotFoundError:
            continue
        for item in dist.files or []:
            if any(word in item.name.lower() for word in ("license", "copying", "notice")) and not item.name.endswith(".py"):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    folder = licenses / dist_name
                    folder.mkdir(exist_ok=True)
                    shutil.copy2(str(source), str(folder / item.name))
    vendor = ROOT / "vendor" / "wb32-dfu-updater-master" / "LICENSE"
    if vendor.exists():
        shutil.copy2(str(vendor), str(licenses / "WB32-Apache-2.0.txt"))
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(str(python_license), str(licenses / "Python-LICENSE.txt"))
    libusb_license = ROOT / "licenses" / "libusb-COPYING.txt"
    if libusb_license.exists():
        shutil.copy2(str(libusb_license), str(licenses / "libusb-LGPL-2.1.txt"))
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed",
               "--name", "QMK-Firmware-Studio", "--collect-binaries", "libusb_package",
               "--collect-data", "libusb_package", "--hidden-import", "usb.backend.libusb1",
               "--hidden-import", "hid", "--exclude-module", "PyQt5", "--exclude-module", "PyQt6",
               "--add-data", "icon.png" + os.pathsep + ".",
               "--add-data", "drivers" + os.pathsep + "drivers",
               "--add-data", str(licenses) + os.pathsep + "licenses",
               "--add-data", "THIRD_PARTY_NOTICES.md" + os.pathsep + "."]
    if args.clean:
        command.append("--clean")
    if sys.platform.startswith("linux"):
        # setuptools' vendored jaraco.context imports this namespace lazily;
        # the pkg_resources runtime hook needs it in the frozen application.
        command.extend(["--hidden-import", "backports", "--collect-submodules", "backports.tarfile"])
    if sys.platform == "darwin":
        command.extend(["--onedir", "--osx-bundle-identifier", "local.qmk.firmwarestudio"])
    else:
        command.append("--onefile")
    icon = ROOT / "assets" / "app.ico"
    if sys.platform == "win32" and icon.exists():
        command.extend(["--icon", str(icon)])
    mac_icon = ROOT / "assets" / "app.icns"
    if sys.platform == "darwin" and mac_icon.exists():
        command.extend(["--icon", str(mac_icon)])
    command.append("main.py")
    subprocess.check_call(command)
    target = ("windows-x64" if sys.platform == "win32" else
              ("macos-arm64" if platform.machine() == "arm64" else "macos-x64") if sys.platform == "darwin" else "linux-x64")
    release = ROOT / "release" / target
    release.mkdir(parents=True, exist_ok=True)
    name = "QMK-Firmware-Studio" + (".exe" if sys.platform == "win32" else ".app" if sys.platform == "darwin" else "")
    built = ROOT / "dist" / name
    sys.path.insert(0, str(ROOT))
    from qmk_updater.runtimes import create_runtime_archive
    create_runtime_archive(built, ROOT / "release" / (target + ".qmk-runtime.zip"), target)
    destination = release / name
    if built.is_dir():
        if destination.exists():
            raise SystemExit("Release app already exists; choose a new release directory before rebuilding.")
        shutil.copytree(str(built), str(destination), symlinks=True)
    else:
        shutil.copy2(str(built), str(destination))
    for file in ("README.md", "THIRD_PARTY_NOTICES.md", "LICENSE", "NOTICE"):
        shutil.copy2(str(ROOT / file), str(release / file))
    shutil.copytree(str(licenses), str(release / "licenses"), dirs_exist_ok=True)
    permissions = ROOT / "drivers"
    if permissions.exists():
        shutil.copytree(str(permissions), str(release / "drivers"), dirs_exist_ok=True)
    print("Native release: " + str(release))


if __name__ == "__main__":
    main()
