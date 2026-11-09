"""Compact maker and customer windows, sharing the same native Qt controls."""
from pathlib import Path

from . import __version__
from .qt import *
from .ui import ROOT, Card, label, button, field, form_field, show_licenses, connection_help


def compact_field(text="", placeholder="", mono=False):
    widget = field(text, placeholder, mono)
    widget.setMinimumHeight(30)
    widget.setMaximumHeight(32)
    return widget


class Panel(Card):
    def __init__(self, title="", subtitle=""):
        super().__init__(title, subtitle)
        self.box.setContentsMargins(16, 12, 16, 12)
        self.box.setSpacing(8)


def apply_compact_theme(widget, accent="#83ADF2", customer=False):
    if customer:
        background, panel, border, text, muted, edit = "#F4F7FC", "#FFFFFF", "#D5DFEB", "#183757", "#647D98", "#FFFFFF"
        hover, track, log_text = "#EAF0F9", "#E3E9F2", "#294764"
    else:
        background, panel, border, text, muted, edit = "#101D2E", "#1A2A3E", "#38516E", "#EDF3FB", "#A8BDDB", "#101D2E"
        hover, track, log_text = "#2C425E", "#0D1928", "#BDCEE5"
    primary_text = "#10263E" if QColor(accent).lightness() > 160 else "#FFFFFF"
    widget.setStyleSheet("""
        QWidget { background: BG; color: TEXT; font-family: 'Microsoft YaHei UI', 'PingFang SC', 'Noto Sans CJK SC', sans-serif; font-size: 12px; }
        QFrame#card { background: PANEL; border: 1px solid BORDER; border-radius: 12px; }
        QFrame#card QLabel, QFrame#card QCheckBox, QFrame#card QRadioButton { background: transparent; border: 0; }
        QLabel { background: transparent; }
        QLabel#title { font-size: 26px; font-weight: 700; }
        QLabel#cardTitle { font-size: 14px; font-weight: 600; }
        QLabel#muted, QLabel#fieldLabel { color: MUTED; font-size: 11px; }
        QLabel#tiny { color: MUTED; font-size: 10px; }
        QLabel#hero { font-size: 17px; font-weight: 700; }
        QLabel#monoLabel { font-family: 'Consolas', monospace; font-size: 15px; color: ACCENT; font-weight: 600; }
        QLabel#badge { color: ACCENT; border: 1px solid BORDER; border-radius: 9px; padding: 4px 10px; font-size: 11px; }
        QLabel#warning { color: #C17B13; }
        QLabel#error { color: #D85858; }
        QLabel#success { color: #289477; }
        QLineEdit, QComboBox { background: EDIT; border: 1px solid BORDER; border-radius: 5px; padding: 0 8px; selection-background-color: ACCENT; }
        QLineEdit:focus, QComboBox:focus { border: 1px solid ACCENT; }
        QLineEdit:read-only { color: MUTED; }
        QLineEdit#mono { font-family: 'Consolas', monospace; }
        QComboBox { min-height: 30px; padding-right: 22px; }
        QComboBox::drop-down { border: 0; width: 20px; }
        QComboBox QAbstractItemView { background: PANEL; color: TEXT; selection-background-color: HOVER; }
        QPushButton { background: PANEL; color: TEXT; border: 1px solid BORDER; border-radius: 6px; padding: 0 13px; min-height: 28px; }
        QPushButton:hover { background: HOVER; border-color: ACCENT; }
        QPushButton#primary { background: ACCENT; color: PRIMARY_TEXT; border: 0; font-weight: 600; min-height: 40px; }
        QPushButton#primary:disabled { background: ACCENT; color: PRIMARY_TEXT; }
        QPushButton:disabled { color: MUTED; }
        QPushButton#link { background: transparent; border: 0; padding: 0; color: MUTED; min-height: 22px; }
        QCheckBox, QRadioButton { background: transparent; spacing: 6px; }
        QRadioButton::indicator { width: 12px; height: 12px; border: 1px solid MUTED; border-radius: 7px; background: EDIT; }
        QRadioButton::indicator:checked { border: 3px solid ACCENT; background: PANEL; }
        QCheckBox::indicator { width: 12px; height: 12px; background: EDIT; border: 1px solid MUTED; border-radius: 2px; }
        QCheckBox::indicator:checked { background: ACCENT; border-color: ACCENT; }
        QProgressBar { background: TRACK; color: TEXT; border: 1px solid BORDER; border-radius: 5px; text-align: center; min-height: 22px; max-height: 22px; font-size: 11px; }
        QProgressBar::chunk { background: ACCENT; border-radius: 4px; }
        QPlainTextEdit, QTextEdit { background: EDIT; color: LOG_TEXT; border: 1px solid BORDER; border-radius: 5px; font-family: 'Consolas', 'Microsoft YaHei UI', monospace; font-size: 11px; padding: 7px; }
        QMenu { background: PANEL; border: 1px solid BORDER; padding: 5px; }
        QMenu::item { padding: 7px 18px; }
        QMenu::item:selected { background: HOVER; }
        QToolTip { background: PANEL; color: TEXT; border: 1px solid BORDER; padding: 5px; }
    """.replace("PRIMARY_TEXT", primary_text).replace("LOG_TEXT", log_text)
       .replace("BG", background).replace("PANEL", panel).replace("BORDER", border)
       .replace("TEXT", text).replace("MUTED", muted).replace("EDIT", edit)
       .replace("HOVER", hover).replace("TRACK", track).replace("ACCENT", accent))


def build_maker(window):
    from .maker_layout import build_maker_window
    build_maker_window(window)


def build_updater(window):
    from .appearance import apply_customer_theme
    from .ui import KeyboardArt, line
    package = window.package
    s = package.settings
    window.setWindowTitle(s.product + " — 固件升级")
    window.setWindowIcon(QIcon(str(ROOT / "icon.png")))
    window.resize(650, 810)
    window.setMinimumSize(600, 780)
    outer = QWidget()
    window.setCentralWidget(outer)
    box = QVBoxLayout(outer)
    box.setContentsMargins(36, 25, 36, 22)
    box.setSpacing(12)
    header = QHBoxLayout()
    logo = QLabel()
    logo.setPixmap(QPixmap(str(ROOT / "icon.png")).scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    header.addWidget(logo)
    header.addSpacing(8)
    header.addWidget(label("FIRMWARE UPDATE", "eyebrow"))
    header.addStretch()
    header.addWidget(label("连续烧录" if window.session.continuous else "单次升级", "badge"))
    box.addLayout(header)
    box.addSpacing(4)
    box.addWidget(label("让键盘，焕然一新。", "title"))
    box.addWidget(label("连接 USB 数据线，剩下的交给我们。", "muted"))
    card = Card()
    card.box.setContentsMargins(20, 17, 20, 17)
    card.box.setSpacing(12)
    row = QHBoxLayout()
    row.addWidget(label(s.product, "cardTitle", True), 1)
    row.addWidget(label("v" + s.version, "badge"))
    card.box.addLayout(row)
    art = KeyboardArt(s.accent)
    art.setMinimumHeight(145)
    art.setMaximumHeight(145)
    card.box.addWidget(art)
    card.box.addWidget(line())
    row = QHBoxLayout()
    row.addWidget(label("WB32FQ95  ·  %.2f KiB" % (package.firmware.size / 1024), "muted"))
    row.addStretch()
    row.addWidget(label("✓  固件完整性校验通过", "accent"))
    card.box.addLayout(row)
    box.addWidget(card)
    window.connection = label("识别到键盘后自动升级。" if s.auto_start else "连接键盘后，点击下方开始升级。", "muted", True)
    box.addWidget(window.connection)
    window.counts = label("成功 0   /   失败 0", "muted")
    if window.session.continuous:
        box.addWidget(window.counts)
    else:
        window.counts.hide()
    row = QHBoxLayout()
    for title in ("01  连接键盘", "02  自动进入 Boot", "03  写入与校验"):
        row.addWidget(label(title, "tiny"))
    box.addLayout(row)
    window.progress_bar = QProgressBar()
    window.progress_bar.setRange(0, 100)
    window.progress_bar.setValue(0)
    window.progress_bar.setTextVisible(True)
    window.progress_bar.setFormat("%p%")
    box.addWidget(window.progress_bar)
    window.message = label("准备就绪", "cardTitle", True)
    box.addWidget(window.message)
    window.start_button = button("等待键盘连接…", True)
    window.start_button.clicked.connect(window.action_clicked)
    box.addWidget(window.start_button)
    window.note = label("", "warning", True)
    box.addWidget(window.note)
    row = QHBoxLayout()
    window.log_toggle = button("查看升级日志")
    window.log_toggle.setObjectName("link")
    window.log_toggle.clicked.connect(window.toggle_log)
    row.addWidget(window.log_toggle)
    save = button("导出日志")
    save.setObjectName("link")
    save.clicked.connect(window.save_log)
    row.addWidget(save)
    row.addStretch()
    help_button = button("连接帮助")
    help_button.setObjectName("link")
    help_button.clicked.connect(lambda: connection_help(window, s))
    row.addWidget(help_button)
    license_button = button("软件许可")
    license_button.setObjectName("link")
    license_button.clicked.connect(lambda: show_licenses(window))
    row.addWidget(license_button)
    box.addLayout(row)
    window.log = QPlainTextEdit()
    window.log.setReadOnly(True)
    window.log.setMaximumBlockCount(2000)
    window.log.setMinimumHeight(105)
    window.log.setMaximumHeight(135)
    window.log.hide()
    box.addWidget(window.log)
    foot = label("QMK FIRMWARE STUDIO  /  " + __version__, "tiny")
    foot.setAlignment(Qt.AlignCenter)
    box.addWidget(foot)
    window.help_buttons = [help_button, license_button]
    apply_customer_theme(window, s.background, s.accent)
