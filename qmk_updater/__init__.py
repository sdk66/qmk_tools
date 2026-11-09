"""Cross-platform QMK/WB32 firmware package maker and updater."""

__version__ = "1.6.0"

# One release version drives the UI, Windows filename and file properties.
WINDOWS_MAKER_STEM = "QMK_Firmware_Toolbox_Package_" + __version__
WINDOWS_MAKER_FILENAME = WINDOWS_MAKER_STEM + ".exe"
