import datetime
import json
import os
import platform
import re
import sys
import tempfile
import traceback
import zipfile
from dataclasses import asdict, fields
from pathlib import Path

from . import __version__
from .devices import Hardware
from .firmware import load_firmware, FirmwareError, FLASH_BASE
from .package import (Settings, Package, encode_package, decode_package,
                      create_executable, create_mac_app)
from .qt import *
from .workflow import upgrade
from .session import Detection
from .runtimes import TARGETS, host_target, templates_directory, install_runtime, system_package

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def label(text, name="", wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    if name in ("badge", "status"):
        widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        widget.setAlignment(Qt.AlignCenter)
    widget.setWordWrap(wrap)
    return widget


def line():
    widget = QFrame()
    widget.setObjectName("divider")
    widget.setFixedHeight(1)
    return widget


def button(text, primary=False):
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    widget.setMinimumHeight(40)
    if primary:
        widget.setObjectName("primary")
    return widget


def field(text="", placeholder="", mono=False):
    widget = QLineEdit(text)
    widget.setPlaceholderText(placeholder)
    widget.setMinimumHeight(37)
    if mono:
        widget.setObjectName("mono")
    return widget


def form_field(layout, row, col, title, widget, span=1):
    box = QVBoxLayout()
    box.setSpacing(7)
    box.addWidget(label(title, "fieldLabel"))
    box.addWidget(widget)
    layout.addLayout(box, row, col, 1, span)


def show_licenses(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("软件信息与第三方许可")
    dialog.resize(760, 560)
    box = QVBoxLayout(dialog)
    box.setContentsMargins(20, 20, 20, 20)
    box.addWidget(label("QMK Firmware Studio  " + __version__, "cardTitle"))
    picker = QComboBox()
    text = QTextEdit()
    text.setReadOnly(True)
    files = [ROOT / "THIRD_PARTY_NOTICES.md"]
    directory = ROOT / "licenses"
    if not directory.exists():
        directory = ROOT / "build" / "assets" / "licenses"
    if directory.exists():
        files += sorted(p for p in directory.rglob("*") if p.is_file())
    for path in files:
        picker.addItem(str(path.relative_to(ROOT)) if ROOT in path.parents else path.name, str(path))
    def display(index):
        try:
            text.setPlainText(Path(picker.currentData()).read_text(encoding="utf-8", errors="replace"))
        except OSError as error:
            text.setPlainText(str(error))
    picker.currentIndexChanged.connect(display)
    box.addWidget(picker)
    box.addWidget(text, 1)
    display(0)
    close = button("关闭")
    close.clicked.connect(dialog.accept)
    box.addWidget(close)
    dialog.exec_()


def connection_help(parent, settings):
    dialog = QDialog(parent)
    dialog.setWindowTitle("首次连接帮助")
    dialog.resize(610, 360)
    box = QVBoxLayout(dialog)
    box.setContentsMargins(24, 24, 24, 24)
    box.setSpacing(17)
    box.addWidget(label("准备好 USB 连接", "cardTitle"))
    box.addWidget(label("使用可传输数据的 USB 线，将键盘切到有线模式；关闭 VIA 和其他占用键盘的工具。", "muted", True))
    if sys.platform == "win32":
        box.addWidget(label("WB32 Boot 需要 WinUSB 驱动。首次安装需要管理员权限；已能通过 QMK Toolbox 烧录的电脑通常无需再次安装。", "muted", True))
        box.addWidget(label("只为 WB Device in DFU Mode 安装此驱动，正常键盘接口使用系统 HID 驱动。", "muted", True))
        install = button("安装厂商 WinUSB 驱动…", True)
        if (settings.boot_vid, settings.boot_pid) != (0x342d, 0xdfa0):
            install.setEnabled(False)
            box.addWidget(label("此包修改了 Boot 标识，附带的原厂驱动仅适用于 342D:DFA0，请联系厂家。", "error", True))
        def install_driver():
            try:
                import ctypes
                archive_path = ROOT / "drivers" / "windows" / "WB32-WinUSB-official.zip"
                directory = Path(tempfile.mkdtemp(prefix="qmk-wb32-driver-"))
                with zipfile.ZipFile(str(archive_path)) as archive:
                    for name in archive.namelist():
                        target = (directory / name).resolve()
                        if directory.resolve() not in target.parents and target != directory.resolve():
                            raise FirmwareError("驱动包路径无效。")
                    archive.extractall(str(directory))
                installer = directory / "wb_dfu_usb_driver_v1.0.0.0" / "dpinst_amd64.exe"
                result = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(installer), None, str(installer.parent), 1)
                if result <= 32:
                    raise FirmwareError("驱动安装器未启动，或管理员授权已取消。")
                QMessageBox.information(dialog, "驱动安装器已打开", "请按厂商安装器提示完成安装，再回到升级程序重试。")
            except Exception as e:
                QMessageBox.warning(dialog, "无法启动驱动安装", str(e))
        install.clicked.connect(install_driver)
        box.addWidget(install)
    elif sys.platform.startswith("linux"):
        box.addWidget(label("Linux 首次需要配置当前用户的 USB / hidraw 访问权限。导出规则后请管理员安装到 /etc/udev/rules.d/，重载规则并重新插拔键盘。", "muted", True))
        export = button("导出本包的 Linux 权限规则…", True)
        def export_rule():
            path, _ = QFileDialog.getSaveFileName(dialog, "导出 udev 规则", "70-qmk-wb32.rules", "udev 规则 (*.rules)")
            if path:
                content = ('SUBSYSTEM=="usb", ATTR{idVendor}=="%04x", ATTR{idProduct}=="%04x", MODE="0660", TAG+="uaccess"\n'
                           'KERNEL=="hidraw*", ATTRS{idVendor}=="%04x", ATTRS{idProduct}=="%04x", MODE="0660", TAG+="uaccess"\n') % (
                               settings.boot_vid, settings.boot_pid, settings.app_vid, settings.app_pid)
                Path(path).write_text(content, encoding="utf-8")
        export.clicked.connect(export_rule)
        box.addWidget(export)
    else:
        box.addWidget(label("请允许 macOS 请求的 USB / 键盘访问权限。若系统阻止打开应用，请使用厂家签名和公证的版本。升级期间保持 USB 连接。", "muted", True))
    box.addStretch()
    close = button("返回升级")
    close.clicked.connect(dialog.accept)
    box.addWidget(close)
    dialog.exec_()


class Card(QFrame):
    def __init__(self, title="", subtitle="", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(22, 20, 22, 20)
        self.box.setSpacing(14)
        if title:
            self.box.addWidget(label(title, "cardTitle"))
        if subtitle:
            self.box.addWidget(label(subtitle, "muted", True))


class KeyboardArt(QWidget):
    def __init__(self, accent="#EAC15A", parent=None):
        super().__init__(parent)
        self.accent = accent
        self.setMinimumHeight(145)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = min(self.width() - 16, 315)
        height = width * 0.37
        left, top = (self.width() - width) / 2, (self.height() - height) / 2 + 7
        painter.setPen(QPen(QColor("#414855"), 1))
        painter.setBrush(QColor("#0F1217"))
        painter.drawRoundedRect(QRectF(left, top + 5, width, height), 11, 11)
        painter.setBrush(QColor("#272D37"))
        painter.drawRoundedRect(QRectF(left, top, width, height), 11, 11)
        gap = width * .012
        key = (width - 20 - 14 * gap) / 15
        keyh = (height - 22 - 4 * gap) / 5
        for row in range(5):
            x = left + 10
            for col in range(15):
                if row == 4 and col in (4, 5, 6, 7, 8):
                    continue
                cell_width = key * 6 + gap * 5 if row == 4 and col == 3 else key
                if row == 4 and col >= 9:
                    x = left + 10 + col * (key + gap)
                painter.setBrush(QColor(self.accent) if (row, col) == (0, 0) else QColor("#3B4350"))
                painter.setPen(QPen(QColor("#4A5361"), .6))
                rect = QRectF(x, top + 10 + row * (keyh + gap), cell_width, keyh)
                painter.drawRoundedRect(rect, 2, 2)
                if row < 4:
                    painter.setPen(QPen(QColor("#8992A2"), .65))
                    painter.drawLine(QPointF(x + key * .32, rect.top() + keyh * .4),
                                     QPointF(x + key * .6, rect.top() + keyh * .4))
                x += cell_width + gap
        painter.setPen(QPen(QColor(self.accent), 2))
        painter.drawLine(QPointF(left + width * .72, top + height + 2), QPointF(left + width * .87, top + height + 2))


class ProbeWorker(QThread):
    result = Signal(object, str)

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings

    def run(self):
        try:
            if self.settings is None:
                import hid
                devices = [d for d in hid.enumerate() if d.get("usage_page", 0) >= 0xff00]
            else:
                devices = Hardware().app_devices(self.settings)
            self.result.emit(devices, "")
        except Exception as e:
            self.result.emit([], str(e))


class UpgradeWorker(QThread):
    progress = Signal(int, str)

    def __init__(self, package, parent=None):
        super().__init__(parent)
        self.package = package
        self.log_lines = []
        self.outcome = None
        self.error = ""

    def update(self, percent, message):
        self.log_lines.append("%s  %s" % (datetime.datetime.now().isoformat(timespec="seconds"), message))
        self.progress.emit(percent, message)

    def run(self):
        lock = QLockFile(str(Path(tempfile.gettempdir()) / "qmk-wb32-upgrade.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            self.error = "另一个升级程序正在运行，请等待其结束。"
            return
        try:
            self.outcome = upgrade(self.package, Hardware(), self.update)
        except Exception as e:
            self.log_lines.append(traceback.format_exc())
            self.error = str(e)
        finally:
            lock.unlock()


class DetectionWorker(QThread):
    """Read-only discovery of both old and new APP IDs, plus WB32 Boot."""
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.detection = Detection()
        self.error = ""

    def run(self):
        try:
            hardware = Hardware()
            apps = hardware.app_devices(self.settings)
            same = ((self.settings.app_vid, self.settings.app_pid, self.settings.usage_page, self.settings.usage_id) ==
                    (self.settings.target_vid, self.settings.target_pid, self.settings.target_usage_page, self.settings.target_usage_id))
            targets = apps if same else hardware.app_devices(self.settings, target=True)
            boots = hardware.boot_devices(self.settings)
            self.detection = Detection(len(apps), len(targets), len(boots),
                                       (apps[0].get("product_string") or "") if apps else "")
        except Exception as e:
            self.error = str(e)


def apply_theme(widget, accent="#EAC15A"):
    widget.setStyleSheet("""
        QWidget { background: #11151C; color: #E8ECF3; font-family: 'Microsoft YaHei UI', 'PingFang SC', 'Noto Sans CJK SC', sans-serif; font-size: 12px; }
        QMainWindow, QDialog { background: #11151C; }
        QWidget#sidebar { background: #0C1016; border-right: 1px solid #262C36; }
        QWidget#main, QWidget#scrollBody { background: #11151C; }
        QFrame#card { background: #1A202A; border: 1px solid #2B3340; border-radius: 13px; }
        QFrame#card QLabel, QFrame#card QCheckBox { background: transparent; border: 0; }
        QLabel { background: transparent; }
        QLabel#title { font-size: 28px; font-weight: 700; }
        QLabel#cardTitle { font-size: 14px; font-weight: 600; color: #F5F6F8; }
        QLabel#muted, QLabel#fieldLabel { color: #929EAF; font-size: 11px; }
        QLabel#tiny { color: #647186; font-size: 10px; }
        QLabel#eyebrow { color: ACCENT; font-size: 10px; font-weight: 600; letter-spacing: 2px; }
        QLabel#hero { font-size: 23px; font-weight: 700; }
        QLabel#accent { color: ACCENT; }
        QLabel#badge { background: #343022; border: 1px solid #655633; border-radius: 10px; color: ACCENT; padding: 4px 10px; font-size: 10px; }
        QLabel#status { background: #172A25; color: #7BD4AF; border-radius: 9px; padding: 6px 11px; font-size: 11px; }
        QLabel#error { color: #F79494; }
        QLineEdit, QComboBox { background: #111720; border: 1px solid #343D4B; border-radius: 6px; padding: 0 10px; selection-background-color: #496078; }
        QLineEdit:focus, QComboBox:focus { border: 1px solid ACCENT; }
        QLineEdit:read-only { color: #8996A7; }
        QLineEdit#mono { font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 13px; }
        QComboBox { min-height: 36px; padding-right: 22px; }
        QComboBox::drop-down { border: 0; width: 22px; }
        QComboBox QAbstractItemView { background: #1A202A; color: #E8ECF3; selection-background-color: #343E4E; padding: 4px; }
        QPushButton { background: #252E3B; border: 1px solid #3B4657; border-radius: 7px; padding: 0 15px; color: #E8ECF3; font-weight: 500; }
        QPushButton:hover { background: #303C4D; border-color: #68768A; }
        QPushButton:pressed { background: #182330; }
        QPushButton#primary { background: ACCENT; color: #171A20; border: 0; font-weight: 700; }
        QPushButton#primary:hover { background: #F7D583; }
        QPushButton:disabled { background: #2E3440; color: #667285; border-color: #343D4A; }
        QPushButton#nav { background: #25281F; color: ACCENT; border: 1px solid #484331; text-align: left; padding: 12px 15px; }
        QPushButton#navSecondary { background: transparent; border: 0; color: #9CA8BA; text-align: left; padding: 12px 15px; }
        QPushButton#link { background: transparent; border: 0; color: #AAB6C8; text-align: left; padding: 0; }
        QPushButton#swatch { border-radius: 9px; padding: 0; }
        QCheckBox { spacing: 8px; color: #B4BECD; }
        QCheckBox::indicator { width: 14px; height: 14px; background: #111720; border: 1px solid #536175; border-radius: 3px; }
        QCheckBox::indicator:checked { background: ACCENT; border-color: ACCENT; image: none; }
        QProgressBar { background: #10151D; border: 0; border-radius: 4px; min-height: 7px; max-height: 7px; }
        QProgressBar::chunk { background: ACCENT; border-radius: 4px; }
        QFrame#divider { background: #2B3340; border: 0; }
        QTextEdit { background: #10161F; color: #AEBCCD; border: 1px solid #303A49; border-radius: 7px; font-family: 'Consolas', monospace; font-size: 11px; padding: 10px; }
        QScrollArea { border: 0; background: transparent; }
        QScrollBar:vertical { background: #11151C; width: 7px; }
        QScrollBar::handle:vertical { background: #3B4553; border-radius: 3px; min-height: 25px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QToolTip { background: #263141; color: #ECF0F6; border: 1px solid #526078; padding: 6px; }
    """.replace("ACCENT", accent))


class DeviceDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("读取已连接的 Raw HID 设备")
        self.resize(740, 360)
        self.selected = None
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 24, 24, 24)
        box.addWidget(label("选择键盘的 Raw HID 接口", "cardTitle"))
        box.addWidget(label("这里只读取连接信息，不会发送进 Boot 命令。", "muted"))
        self.list = QListWidget()
        box.addWidget(self.list)
        self.note = label("正在扫描…", "muted")
        box.addWidget(self.note)
        choose = button("使用所选设备", True)
        choose.clicked.connect(self.accept_selection)
        box.addWidget(choose)
        self.worker = ProbeWorker(parent=self)
        self.worker.result.connect(self.populate)
        self.worker.start()

    def populate(self, devices, error):
        self.devices = devices
        self.note.setText(error or ("发现 %d 个厂商自定义 HID 接口" % len(devices)))
        for device in devices:
            self.list.addItem("%s  ·  %04X:%04X  ·  %04X:%04X  ·  接口 %s" % (
                device.get("product_string", "HID"), device["vendor_id"], device["product_id"],
                device.get("usage_page", 0), device.get("usage", 0), device.get("interface_number", "—")))
        if devices:
            self.list.setCurrentRow(0)

    def accept_selection(self):
        index = self.list.currentRow()
        if index >= 0:
            self.selected = self.devices[index]
            self.accept()

    def closeEvent(self, event):
        if self.worker.isRunning():
            event.ignore()
        else:
            event.accept()

    def reject(self):
        if self.worker.isRunning():
            self.worker.finished.connect(super().reject)
        else:
            super().reject()


class MakerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        from .layouts import build_maker
        build_maker(self)

    def set_accent(self, color):
        from .layouts import apply_compact_theme
        self.accent = color
        apply_compact_theme(self, color)

    def refresh_preview(self, *args):
        if not hasattr(self, "mode_hint"):
            return
        continuous = self.continuous_mode.isChecked()
        self.mode_hint.setText("连续：完成后等待更换下一把。" if continuous else "单次：成功退出 DFU 后，倒计时 5 秒关闭。")
        self.customer_preview.update_preview(self.inputs["product"].text(), self.inputs["version"].text(),
                                              self.firmware.size if self.firmware else 0,
                                              self.background_combo.currentData(), self.accent,
                                              self.auto_start.isChecked(), continuous)
        target = self.platform_combo.currentData()
        if target:
            try:
                self.template(target)
                self.platform_status.setText("%s 模板已就绪，可直接生成" % TARGETS[target][0])
            except FirmwareError:
                self.platform_status.setText("需先导入 %s 运行模板，支持在当前电脑装包" % TARGETS[target][0])

    def select_firmware(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Q95 固件", "", "QMK 固件 (*.hex *.bin)")
        if path:
            self.load_firmware(path)

    def load_firmware(self, path):
        try:
            firmware = load_firmware(path, int(self.base.text(), 16))
            self.firmware, self.firmware_path = firmware, Path(path).resolve()
            self.file_label.setText(str(self.firmware_path))
            self.file_label.setToolTip(str(self.firmware_path))
            self.file_meta.setText("%s 字节 · %s" % (format(firmware.size, ","), self.firmware_path.suffix[1:].upper()))
            self.usb_combo.blockSignals(True)
            self.hid_combo.blockSignals(True)
            self.usb_combo.clear()
            self.hid_combo.clear()
            usbs = firmware.usb_candidates()
            hids = firmware.hid_candidates()
            for usb in usbs:
                self.usb_combo.addItem("%04X : %04X  ·  bcdDevice %04X" % (usb.vid, usb.pid, usb.version), usb)
            for hid in hids:
                self.hid_combo.addItem("%04X:%04X · %d B" % (hid.usage_page, hid.usage, hid.report_size), hid)
            if not usbs:
                self.usb_combo.addItem("未识别 · 请手动设置并确认参数")
            elif len(usbs) > 1:
                self.usb_combo.insertItem(0, "发现多个描述符 · 请选择正确的一项")
                self.usb_combo.setCurrentIndex(0)
            if not hids:
                self.hid_combo.addItem("未识别 · 请手动设置并确认参数")
            elif len(hids) > 1:
                self.hid_combo.insertItem(0, "发现多个 Raw HID · 请选择正确的一项")
                self.hid_combo.setCurrentIndex(0)
            self.usb_combo.blockSignals(False)
            self.hid_combo.blockSignals(False)
            self.choose_usb()
            self.choose_hid()
            self.firmware_size.setText(format(firmware.size, ",") + " 字节")
            strings = firmware.strings()
            self.inputs["product"].setText(strings[-1] if strings else self.firmware_path.stem)
            if len(usbs) == 1:
                version = usbs[0].version
                self.inputs["version"].setText("%X.%X.%X" % (version >> 8, (version >> 4) & 15, version & 15))
            else:
                self.inputs["version"].setText("1.0.0")
            self.generate.setEnabled(True)
            self.base.setEnabled(self.firmware_path.suffix.lower() == ".bin")
            if not self.base.isEnabled():
                self.base.setText("%08X" % firmware.base)
            self.apply_base.setEnabled(self.base.isEnabled())
            self.status.setText("固件已载入，请确认键盘参数")
            if len(usbs) > 1 or len(hids) > 1:
                self.status.setText("发现多个接口，请在高级参数中选择")
                self.advanced_dialog.open()
            self.refresh_preview()
        except Exception as e:
            self.firmware = None
            self.generate.setEnabled(False)
            self.status.setText("固件解析失败：%s" % e)
            QMessageBox.warning(self, "固件无法使用", str(e))

    def choose_usb(self, *args):
        usb = self.usb_combo.currentData()
        self.usb_version.setText("0x%04X" % usb.usb_version if usb else "未识别")
        if usb is not None:
            self.inputs["app_vid"].setText("%04X" % usb.vid)
            self.inputs["app_pid"].setText("%04X" % usb.pid)

    def choose_hid(self, *args):
        hid = self.hid_combo.currentData()
        if hid is not None:
            self.inputs["usage_page"].setText("%04X" % hid.usage_page)
            self.inputs["usage_id"].setText("%04X" % hid.usage)
            self.inputs["report_size"].setText(str(hid.report_size))
            self.inputs["report_id"].setText("%02X" % hid.report_id)

    def reload_bin(self):
        if self.firmware_path and self.firmware_path.suffix.lower() == ".bin":
            self.load_firmware(self.firmware_path)

    def read_connected(self):
        dialog = DeviceDialog(self)
        if dialog.exec_() and dialog.selected:
            d = dialog.selected
            for key, value in (("app_vid", d["vendor_id"]), ("app_pid", d["product_id"]),
                               ("usage_page", d.get("usage_page", 0)), ("usage_id", d.get("usage", 0))):
                self.inputs[key].setText("%04X" % value)
            self.status.setText("已读取当前 APP 参数 · 固件的目标标识保持由所选描述符决定")

    def settings(self):
        values = {}
        for key, widget in self.inputs.items():
            value = widget.text().strip()
            try:
                values[key] = value if key in ("product", "version") else int(value, 10 if key == "report_size" else 16)
            except ValueError:
                raise FirmwareError("%s 的格式不正确。" % key)
        values.update(accent=self.accent, auto_start=self.auto_start.isChecked(), allow_boot_recovery=self.boot_recovery.isChecked(),
                      burn_mode="continuous" if self.continuous_mode.isChecked() else "single",
                      background=self.background_combo.currentData())
        usb, hid = self.usb_combo.currentData(), self.hid_combo.currentData()
        if self.firmware and len(self.firmware.usb_candidates()) > 1 and usb is None:
            raise FirmwareError("请先选择固件中的目标 USB 描述符。")
        if self.firmware and len(self.firmware.hid_candidates()) > 1 and hid is None:
            raise FirmwareError("请先选择固件中的目标 Raw HID 描述符。")
        values.update(target_vid=usb.vid if usb else values["app_vid"], target_pid=usb.pid if usb else values["app_pid"],
                      target_usage_page=hid.usage_page if hid else values["usage_page"],
                      target_usage_id=hid.usage if hid else values["usage_id"])
        settings = Settings(**values)
        settings.validate()
        return settings

    def save_project(self):
        try:
            settings = self.settings()
            path, _ = QFileDialog.getSaveFileName(self, "保存制作配置", "qmk-project.json", "JSON 配置 (*.json)")
            if path:
                content = {"settings": asdict(settings), "firmware": str(self.firmware_path or ""),
                           "bin_base": self.base.text(), "usb_index": self.usb_combo.currentIndex(),
                           "hid_index": self.hid_combo.currentIndex()}
                Path(path).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
                self.status.setText("配置已保存")
        except Exception as e:
            QMessageBox.warning(self, "配置未保存", str(e))

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "载入制作配置", "", "JSON 配置 (*.json)")
        if not path:
            return
        try:
            content = json.loads(Path(path).read_text(encoding="utf-8"))
            settings = Settings(**content["settings"])
            settings.validate()
            self.base.setText(content.get("bin_base", "08000000"))
            firmware_path = Path(content["firmware"])
            if not firmware_path.is_absolute():
                firmware_path = Path(path).parent / firmware_path
            if firmware_path.is_file():
                self.load_firmware(firmware_path)
                self.usb_combo.setCurrentIndex(content.get("usb_index", 0))
                self.hid_combo.setCurrentIndex(content.get("hid_index", 0))
            for key, widget in self.inputs.items():
                value = getattr(settings, key)
                widget.setText(str(value) if key in ("product", "version", "report_size") else "%04X" % value)
            self.continuous_mode.setChecked(settings.burn_mode == "continuous")
            self.single_mode.setChecked(settings.burn_mode == "single")
            self.auto_start.setChecked(settings.auto_start)
            background_index = self.background_combo.findData(settings.background)
            if background_index < 0:
                self.background_combo.addItem(settings.background, settings.background)
                background_index = self.background_combo.count() - 1
            self.background_combo.setCurrentIndex(background_index)
            self.boot_recovery.setChecked(settings.allow_boot_recovery)
            self.set_accent(settings.accent)
            self.status.setText("配置已载入 · 请确认固件和设备参数")
        except Exception as e:
            QMessageBox.warning(self, "配置无法载入", str(e))

    def template(self, target):
        if target not in TARGETS:
            raise FirmwareError("请选择客户系统。")
        archive = templates_directory() / (target + ".qmk-runtime.zip")
        if archive.is_file():
            return archive
        if target == host_target() and getattr(sys, "frozen", False):
            exe = Path(sys.executable)
            return exe.parent.parent.parent if sys.platform == "darwin" and exe.parent.name == "MacOS" else exe
        extension = ".exe" if target.startswith("windows") else ".app" if target.startswith("macos") else ""
        local = ROOT / "dist" / ("QMK-Firmware-Studio" + extension)
        if target == host_target() and local.exists():
            return local
        raise FirmwareError("请先导入 %s 系统模板；导入后可在当前电脑生成对应升级包。" % TARGETS[target][0])

    def import_runtime(self):
        source, _ = QFileDialog.getOpenFileName(self, "导入一个或全部系统的运行模板", "", "系统模板 (*.qmk-runtime.zip *.zip)")
        if not source:
            return
        try:
            targets = install_runtime(source, templates_directory())
            if len(targets) == 1:
                self.platform_combo.setCurrentIndex(self.platform_combo.findData(targets[0]))
            self.refresh_preview()
            self.status.setText("系统模板已导入")
        except Exception as error:
            QMessageBox.warning(self, "模板未导入", str(error))

    def generate_package(self):
        try:
            if not self.firmware:
                raise FirmwareError("请先选择固件。")
            # Re-read the source to catch a firmware file replaced after preview.
            current = load_firmware(self.firmware_path, int(self.base.text(), 16))
            if current.source_sha256 != self.firmware.source_sha256 or current.segments != self.firmware.segments:
                raise FirmwareError("固件文件或 BIN 地址已改变，请重新载入后再生成。")
            settings = self.settings()
            if not self.firmware.usb_candidates() or not self.firmware.hid_candidates():
                answer = QMessageBox.question(self, "请确认手动参数", "固件未能完整识别 USB / Raw HID 描述符。确定使用当前手动参数，同时将其用作升级后的重连标识？")
                if answer != QMessageBox.Yes:
                    return
            data = encode_package(Package(settings, self.firmware))
            target = self.platform_combo.currentData()
            safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", settings.product).strip(". ") or "QMK"
            safe_version = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", settings.version).strip(". ")
            stem = safe_name + "-" + safe_version + ("_factory" if settings.burn_mode == "continuous" else "_updater")
            template = self.template(target)
            extension = TARGETS[target][1]
            destination, _ = QFileDialog.getSaveFileName(self, "生成 %s 升级包" % TARGETS[target][0], stem + extension)
            if destination:
                if not destination.lower().endswith(extension):
                    destination += extension
                system_package(template, destination, data, target)
            if destination:
                self.status.setText("已生成：%s" % destination)
                start = "打开后识别键盘即开始。" if settings.auto_start else "打开后需点击开始按钮。"
                description = start + ("完成后等待更换下一把。" if settings.burn_mode == "continuous" else
                                       "成功退出 DFU 后倒计时 5 秒关闭。")
                QMessageBox.information(self, "升级包制作完成", description + "\n\n" + destination)
        except Exception as e:
            QMessageBox.warning(self, "升级包未生成", str(e))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.load_firmware(urls[0].toLocalFile())

