"""Generate PyInstaller's Windows version resource from the release version.

This module is deliberately platform independent. PyInstaller evaluates the
returned resource on Windows; creating it does not load any Windows APIs.
"""
import re


def windows_version_resource(version, filename):
    """Return UTF-8-safe source for ``PyInstaller --version-file``.

    Release versions use three numeric components. Windows' fixed version
    fields require four unsigned 16-bit values, so the final component is zero.
    The visible strings retain the same release version used by the filename.
    """
    if not isinstance(version, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError("Windows release version must contain three numeric components")
    parts = tuple(int(part) for part in version.split("."))
    if any(part > 65535 for part in parts):
        raise ValueError("Windows version components must be between 0 and 65535")
    if (not isinstance(filename, str) or not filename.lower().endswith(".exe")
            or filename == ".exe" or any(char in filename for char in '/\\:')
            or any(ord(char) < 32 for char in filename)):
        raise ValueError("OriginalFilename must be an executable basename")
    fixed_version = parts + (0,)
    strings = {
        "FileDescription": "QMK Firmware Toolbox Package",
        "FileVersion": version,
        "InternalName": filename[:-4],
        "OriginalFilename": filename,
        "ProductName": "QMK Firmware Toolbox Package",
        "ProductVersion": version,
    }
    entries = ",\n".join("                StringStruct(%r, %r)" % item
                           for item in strings.items())
    return ("# UTF-8\n"
            "VSVersionInfo(\n"
            "    ffi=FixedFileInfo(\n"
            "        filevers=%r,\n"
            "        prodvers=%r,\n"
            "        mask=0x3f, flags=0, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)\n"
            "    ),\n"
            "    kids=[\n"
            "        StringFileInfo([\n"
            "            StringTable('040904B0', [\n%s\n"
            "            ])\n"
            "        ]),\n"
            "        VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
            "    ]\n"
            ")\n") % (fixed_version, fixed_version, entries)
