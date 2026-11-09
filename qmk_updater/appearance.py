"""Customer-only colors and a passive preview. No device discovery."""
from .qt import *
from .ui import ROOT, Card, KeyboardArt, label, button

BACKGROUNDS = [("白色", "#FFFFFF"), ("浅蓝", "#F1F6FF"), ("暖白", "#FFF9EE"), ("深色", "#11151C")]


def customer_colors(background):
    dark = QColor(background).lightness() < 140
    return {"background": background, "card": "#1B222D" if dark else "#F7F9FC",
            "text": "#EDF2FA" if dark else "#18334E", "muted": "#9EACC0" if dark else "#708299",
            "border": "#303A49" if dark else "#DFE7F0", "track": "#0C131D" if dark else "#E9EFF6",
            "log": "#111923" if dark else "#FFFFFF", "warning": "#D99A2B" if dark else "#A86C09"}


def apply_customer_theme(widget, background, accent):
    colors = customer_colors(background)
    style = """
        QWidget { background: BACKGROUND; color: FOREGROUND; font-family: 'Microsoft YaHei UI', 'PingFang SC', 'Noto Sans CJK SC', sans-serif; font-size: 12px; }
        QLabel { background: transparent; }
        QLabel#title { font-size: 27px; font-weight: 700; }
        QLabel#cardTitle { font-size: 14px; font-weight: 600; }
        QLabel#muted, QLabel#fieldLabel { color: MUTED; font-size: 11px; }
        QLabel#tiny { color: MUTED; font-size: 10px; }
        QLabel#eyebrow { color: ACCENT; font-size: 10px; letter-spacing: 2px; font-weight: 600; }
        QLabel#accent { color: ACCENT; }
        QLabel#badge { color: ACCENT; border: 1px solid BORDER; border-radius: 9px; padding: 4px 9px; font-size: 10px; }
        QLabel#warning { color: WARNING; font-size: 10px; }
        QFrame#card { background: CARD; border: 1px solid BORDER; border-radius: 13px; }
        QFrame#card QLabel { background: transparent; border: 0; }
        QFrame#customerPreview { border: 1px solid BORDER; border-radius: 12px; }
        QFrame#divider { background: BORDER; border: 0; max-height: 1px; }
        QPushButton { background: CARD; color: FOREGROUND; border: 1px solid BORDER; border-radius: 7px; padding: 0 12px; min-height: 32px; }
        QPushButton#primary, QPushButton#primary:disabled { background: ACCENT; color: #14283D; border: 0; min-height: 44px; font-weight: 600; }
        QPushButton#link { background: transparent; color: MUTED; border: 0; padding: 0; min-height: 23px; font-size: 11px; }
        QProgressBar { background: TRACK; color: FOREGROUND; border: 1px solid BORDER; border-radius: 5px; min-height: 21px; max-height: 21px; text-align: center; font-size: 11px; }
        QProgressBar::chunk { background: ACCENT; border-radius: 4px; }
        QPlainTextEdit, QTextEdit { background: LOG; color: FOREGROUND; border: 1px solid BORDER; border-radius: 7px; padding: 7px; font-size: 11px; }
        QComboBox { background: CARD; border: 1px solid BORDER; border-radius: 5px; padding: 6px; }
    """
    for token, value in [("BACKGROUND", colors["background"]), ("FOREGROUND", colors["text"]),
                         ("MUTED", colors["muted"]), ("BORDER", colors["border"]),
                         ("CARD", colors["card"]), ("TRACK", colors["track"]), ("LOG", colors["log"]),
                         ("WARNING", colors["warning"]), ("ACCENT", accent)]:
        style = style.replace(token, value)
    widget.setStyleSheet(style)


class CustomerPreview(QFrame):
    """Read-only release information using the maker's own panel colors."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(254)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        def panel(title):
            card = Card(title)
            card.box.setContentsMargins(15, 13, 15, 13)
            card.box.setSpacing(10)
            return card
        release = panel("发布预览")
        self.system = label("", "muted", True)
        self.filename = label("等待选择固件", "hero", True)
        self.filename.setTextFormat(Qt.PlainText)
        self.firmware = label("", "tiny", True)
        self.mode = label("", "muted", True)
        self.startup = label("", "muted", True)
        for widget in (self.system, self.filename, self.firmware, self.mode, self.startup):
            release.box.addWidget(widget)
        release.box.addStretch()
        box.addWidget(release, 2)
        flow = panel("设备连接流程")
        flow.box.addWidget(label("当前设备 · APP", "muted"))
        self.app_ids = label("", "monoLabel")
        flow.box.addWidget(self.app_ids)
        flow.box.addWidget(label("↓  自动进入 Boot，写入后重启一次", "muted", True))
        self.boot_ids = label("", "monoLabel")
        flow.box.addWidget(self.boot_ids)
        box.addWidget(flow, 1)
        info = panel("参数说明")
        info.box.addWidget(label("APP 标识可按当前键盘修改，Boot 标识独立保存。", "muted", True))
        self.address = label("", "muted")
        self.background_label = label("", "muted")
        info.box.addWidget(self.address)
        info.box.addWidget(self.background_label)
        info.box.addStretch()
        box.addWidget(info, 1)

    def update_preview(self, product, version, size, background, accent, auto_start, continuous,
                       filename="", target_label="", firmware_name="", app_ids="", boot_ids="", address=""):
        self.system.setText(target_label + (" · 连续烧录" if continuous else " · 单次烧录"))
        self.filename.setText(filename if size else "等待选择固件")
        self.firmware.setText("内置固件：%s\n%s 字节" % (firmware_name, format(size, ",")) if size else "生成文件自带固件和设备参数。")
        self.mode.setText("完成后等待更换下一把，窗口保持打开。" if continuous else "成功后显示 5 秒倒计时，随后自动关闭。")
        self.startup.setText("打开后自动识别并开始。" if auto_start else "打开后点击开始按钮。")
        self.app_ids.setText(app_ids)
        self.boot_ids.setText("BOOT  " + boot_ids)
        self.address.setText("APP 地址  0x" + address)
        names = {value.upper(): name for name, value in BACKGROUNDS}
        self.background_label.setText("客户页背景：" + names.get(background.upper(), background))
