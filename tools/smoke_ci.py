"""Verify frozen customer startup on its actual CI operating system."""
import argparse
import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--target", required=True)
args = parser.parse_args()
target = args.target
release = ROOT / "release" / target
work = ROOT / "build" / "native-smoke"
work.mkdir(parents=True, exist_ok=True)
name = "SAMURAI-S751-v0.0.9"
if target.startswith("macos"):
    subprocess.check_call(["/usr/bin/unzip", "-q", str(release / (name + ".zip")), "-d", str(work)])
    app = work / name / (name + ".app")
    subprocess.check_call(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])
    executable = app / "Contents" / "MacOS" / "QMK-Firmware-Studio"
elif target.startswith("linux"):
    executable = work / name
    with tarfile.open(str(release / (name + ".tar.gz"))) as archive:
        member, = archive.getmembers()
        executable.write_bytes(archive.extractfile(member).read())
    executable.chmod(0o755)
else:
    executable = release / (name + ".exe")
env = os.environ.copy()
env["QT_QPA_PLATFORM"] = "offscreen"
env["PYUSB_DEBUG"] = "debug"
env["LIBUSB_DEBUG"] = "4"
if target.startswith("linux"):
    # This old libusb release requires a non-empty USB bus directory even on
    # a headless runner. An empty bus folder is sufficient; no device is made.
    usb_bus = Path("/dev/bus/usb")
    if not usb_bus.exists() or not any(not p.name.startswith(".") for p in usb_bus.iterdir()):
        subprocess.check_call(["sudo", "mkdir", "-p", "/dev/bus/usb/001"])
    subprocess.check_call([sys.executable, str(ROOT / "main.py"), "--diagnostics",
                           str(work / "source-diagnostics.json")], env=env)
subprocess.check_call([sys.executable, str(ROOT / "tools" / "smoke_test.py"), str(executable),
                       "--output", str(work / "results")], env=env)
