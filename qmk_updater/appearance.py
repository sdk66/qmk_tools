"""Customer-only colors and a passive preview. No device discovery."""
from .qt import *
from .ui import ROOT, Card, KeyboardArt, label, button

BACKGROUNDS = [("白色", "#FFFFFF"), ("浅蓝", "#F1F6FF"), ("暖白", "#FFF9EE"), ("深色", "#11151C")]


def customer_colors(background):
    dark = QColor(background).lightness() < 140
    return {"background": background, "card": "#1B222D" if dark else "#F7F9FC",
            "text": "#EDF2FA" if dark else "#18334E", "muted": "#9EACC0" if dark else "#708299",
            "border": "#303A49" if dark else "#DFE7F0", "track": "#0C131D" if dark else "#E9EFF6",
            "log": "#111923" if dark else "#FFFFFF"}


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
        QLabel#warning { color: MUTED; font-size: 10px; }
        QFrame#card { background: CARD; border: 1px solid BORDER; border-radius: 13px; }
        QFrame#card QLabel { background: transparent; border: 0; }
        QFrame#customerPreview { border: 1px solid BORDER; border-radius: 12px; }
        QFrame#divider { background: BORDER; border: 0; max-height: 1px; }
        QPushButton { background: CARD; color: FOREGROUND; border: 1px solid BORDER; border-radius: 7px; padding: 0 12px; min-height: 32px; }
        QPushButton#primary, QPushButton#primary:disabled { background: ACCENT; color: #14283D; border: 0; min-height: 44px; font-weight: 600; }
        QPushButton#link { background: transparent; color: MUTED; border: 0; padding: 0; min-height: 23px; font-size: 11px; }
        QProgressBar { background: TRACK; color: FOREGROUND; border: 1px solid BORDER; border-radius: 5px; min-height: 21px; max-height: 21px; text-align: center; font-size: 11px; }
        QProgressBar::chunk { background: ACCENT; border-radius: 4px; }
        QPlainTextEdit, QTextEdit { background: LOG; color: MUTED; border: 1px solid BORDER; border-radius: 7px; padding: 7px; font-size: 11px; }
        QComboBox { background: CARD; border: 1px solid BORDER; border-radius: 5px; padding: 6px; }
    """
    for token, value in [("BACKGROUND", colors["background"]), ("FOREGROUND", colors["text"]),
                         ("MUTED", colors["muted"]), ("BORDER", colors["border"]),
                         ("CARD", colors["card"]), ("TRACK", colors["track"]), ("LOG", colors["log"]), ("ACCENT", accent)]:
        style = style.replace(token, value)
    widget.setStyleSheet(style)


class CustomerPreview(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("customerPreview")
        self.setFixedWidth(254)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 16, 14, 16)
        box.setSpacing(12)
        box.addWidget(label("升级页预览", "eyebrow"))
        title = label("让键盘，焕然一新。", "cardTitle")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        box.addWidget(title)
        self.product = label("选择固件后预览", "cardTitle", True)
        card = Card()
        card.box.setContentsMargins(12, 12, 12, 12)
        card.box.setSpacing(8)
        card.box.addWidget(self.product)
        self.art = KeyboardArt()
        self.art.setMinimumHeight(105)
        self.art.setMaximumHeight(105)
        card.box.addWidget(self.art)
        self.version = label("", "muted")
        card.box.addWidget(self.version)
        box.addWidget(card)
        box.addWidget(label("升级进度", "muted"))
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setFormat("%p%")
        progress.setTextVisible(True)
        box.addWidget(progress)
        self.mode = label("单次烧录 · 成功后 5 秒关闭", "muted", True)
        box.addWidget(self.mode)
        self.action = button("等待键盘连接…", True)
        self.action.setAttribute(Qt.WA_TransparentForMouseEvents)
        box.addWidget(self.action)
        box.addStretch()
        box.addWidget(label("仅预览打包后的界面", "tiny"))

    def update_preview(self, product, version, size, background, accent, auto_start, continuous):
        self.product.setText(product or "选择固件后预览")
        self.version.setText("v%s  ·  %.2f KiB" % (version or "—", size / 1024))
        self.mode.setText("连续烧录 · 完成后等待下一把" if continuous else "单次烧录 · 成功后 5 秒关闭")
        self.action.setText("等待键盘连接…" if auto_start else "一键升级  →")
        self.art.accent = accent
        self.art.update()
        apply_customer_theme(self, background, accent)
