"""Portable names for customer upgrade packages, independent of device metadata."""
import os
import re


_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3]|CONIN\$|CONOUT\$)(?:\.|$)", re.IGNORECASE)
_PACKAGE_SUFFIXES = (".tar.gz", ".exe", ".zip")


def _portable_stem(name, fallback):
    name = _INVALID.sub("_", str(name)).strip(" .")
    if not name:
        name = _INVALID.sub("_", str(fallback)).strip(" .") or "firmware"
    if _RESERVED.match(name):
        name = "_" + name
    return name


def firmware_stem(path, fallback="firmware"):
    """Use a HEX/BIN basename plus ``_update`` as the editable default.

    Both Windows and POSIX separators are understood, even when a firmware
    filename originates on a different operating system from the packager.
    """
    name = os.fspath(path).replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().endswith((".hex", ".bin")):
        name = name[:-4]
    name = _portable_stem(name, fallback)
    return name if name.lower().endswith("_update") else name + "_update"


def package_filename(name, extension, fallback="firmware"):
    """Add the selected target suffix to an editable, portable filename.

    A previously entered package suffix is replaced when the target changes.
    For example, ``keyboard.exe`` becomes ``keyboard.zip`` for macOS, while
    applying the same target twice keeps the same filename.
    """
    extension = extension.lower()
    if extension not in _PACKAGE_SUFFIXES:
        raise ValueError("Unsupported package extension: " + extension)
    name = _INVALID.sub("_", str(name)).strip().rstrip(". ")
    for suffix in _PACKAGE_SUFFIXES:
        if name.lower().endswith(suffix):
            name = name[:-len(suffix)]
            break
    return _portable_stem(name, fallback) + extension
