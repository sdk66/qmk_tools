# Third-party notices

This application uses the following components. Distribution includes their
license texts in the `licenses` directory (also embedded by the native build).

- **WB32 protocol implementation**: Derived from `dfufwdevice.c` and `dfufw.c`
  in https://github.com/WestberryTech/wb32-dfu-updater . Copyright (C) 2021
  Westberry Technology (ChangZhou) Corp., Ltd. Apache License, Version 2.0.
  The Python adaptation adds strict validation, sparse page preservation and
  progress reporting; it does not automatically disable read protection.
- **PySide2 / PySide6 and Qt**: Copyright The Qt Company Ltd. and contributors.
  The open-source Qt for Python distributions are used under LGPLv3 and the
  applicable bundled component licenses. https://www.qt.io/licensing/
  https://code.qt.io/pyside/pyside-setup.git/
  https://code.qt.io/qt/qtbase.git/
  Libraries are dynamically loaded. Corresponding sources are available from
  the upstream repositories at the bundled dependency versions. This project
  does not restrict reverse engineering for debugging modifications of these
  libraries; a user may rebuild the application with modified libraries.
- **hidapi / cython-hidapi**: HIDAPI permits BSD, GPLv3 or its original HIDAPI
  license; use is under the BSD option. The Cython binding is BSD licensed.
  https://github.com/libusb/hidapi and https://github.com/trezor/cython-hidapi
- **PyUSB**: BSD-3-Clause. https://github.com/pyusb/pyusb
- **libusb**: LGPL-2.1-or-later. https://github.com/libusb/libusb
- **libusb-package**: Apache-2.0 wrapper with the included libusb library under
  its own LGPL license. https://github.com/pyocd/libusb-package
- **PyInstaller**: GPL with its exception permitting distribution of bundled
  applications under other licenses. https://pyinstaller.org/
- **Python**: Python Software Foundation License. https://www.python.org/

The provided logo and firmware are user-supplied assets; this repository's
source code license does not relicense these assets. The Windows WinUSB
driver archive is an unmodified copy from the WB32 vendor repository and
retains its original licensing and signatures.
