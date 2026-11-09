"""Automatic customer updater and factory station UI."""
import datetime
from collections import deque
from pathlib import Path

from .qt import *
from .session import BurnSession
from .ui import UpgradeWorker, DetectionWorker


class UpdaterWindow(QMainWindow):
    def __init__(self, package, safe_preview=False):
        super().__init__()
        self.package = package
        self.session = BurnSession(package.settings)
        self.safe_preview = safe_preview
        self.worker = None
        self.probe = None
        self.busy = False
        self._closing = False
        self._probe_close_connected = False
        self._last_log_bucket = None
        self._last_probe_error = ""
        self.log_lines = deque(maxlen=50000)
        from .layouts import build_updater
        build_updater(self)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.probe_device)
        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self.countdown_tick)
        self.append_log("升级包完整性校验通过，内置固件：" + package.firmware.name)
        self.append_log("自动等待匹配 VID / PID / Usage Page / Usage ID 的键盘。")
        self.note.setText(self.mode_note())
        self.refresh_action()
        if safe_preview:
            self.connection.setText("预览模式 · 设备通信已禁用")
            self.start_button.setEnabled(False)
        else:
            self.timer.start()
            QTimer.singleShot(100, self.probe_device)

    def mode_note(self):
        if self.session.continuous:
            return "连续烧录：成功退出 DFU 后，拔下本把并等待提示，再连接下一把。\n烧录期间请勿断电或拔出 USB。"
        return "单次烧录：成功退出 DFU 并确认重连后，倒计时 5 秒自动关闭。\n烧录期间请勿断电或拔出 USB。"

    def append_log(self, message):
        text = datetime.datetime.now().strftime("%H:%M:%S") + "  " + message
        self.log_lines.append(text)
        self.log.appendPlainText(text)

    def probe_device(self):
        if (self.safe_preview or self._closing or self.busy or self.session.state in ("starting", "countdown", "done")
                or (self.probe and self.probe.isRunning())):
            return
        if self.probe:
            self.probe.deleteLater()
        self.probe = DetectionWorker(self.package.settings, self)
        probe = self.probe
        probe.finished.connect(lambda: self.probe_finished(probe))
        self.probe.start()

    def probe_finished(self, probe):
        if not self._closing and probe is self.probe:
            self.consume_detection(probe.detection, probe.error)

    def consume_detection(self, detection, error=""):
        if self.busy or self._closing or self.session.state in ("countdown", "done"):
            return
        if error:
            self.connection.setText("连接检查失败：" + error)
            if error != self._last_probe_error:
                self.append_log("连接检查失败：" + error)
            self._last_probe_error = error
            return
        self._last_probe_error = ""
        action = self.session.observe(detection)
        if action == "start":
            self.connection.setText("已找到目标键盘，正在自动开始升级…")
            QTimer.singleShot(0, self.start_upgrade)
        elif action == "ready":
            self.message.setText("键盘已连接，等待开始")
            self.connection.setText("点击下方「开始连续烧录」后启动工厂烧录。" if self.session.continuous else
                                    "点击下方「开始升级」后开始写入固件。")
        elif action == "multiple":
            self.message.setText("检测到多个匹配设备")
            self.connection.setText("请只保留一把待烧录键盘，程序会自动继续。")
        elif action == "boot_blocked":
            self.message.setText("设备已在 Boot / DFU 模式")
            self.connection.setText("此包未允许直接从 Boot 恢复，请使用对应型号的恢复升级包。")
        elif action == "remove":
            self.message.setText("本把烧录成功，等待更换下一把")
            self.connection.setText("请拔下已完成的键盘，等待「可连接下一把」提示。")
        elif action == "next":
            self.progress_bar.setValue(0)
            self.message.setText("可连接下一把键盘" if self.session.continuous else "正在等待设备连接…")
            self.connection.setText("检测到目标键盘后将自动开始升级。" if self.session.enabled else
                                    "连接键盘后点击开始按钮进行升级。")
            self.note.setText(self.mode_note())
            self.append_log("已检测到设备拔出，可连接下一把。")
        elif action == "paused":
            self.message.setText("自动烧录已暂停")
            self.connection.setText("点击下方「继续自动烧录」恢复。")
        elif action == "waiting":
            self.message.setText("正在等待设备连接…")
            self.connection.setText("请使用 USB 数据线连接目标键盘，程序会自动开始。" if self.session.enabled else
                                    "请连接目标键盘，再点击下方开始按钮。")
        self.refresh_action()

    def start_upgrade(self):
        if self.safe_preview or self._closing or self.busy or self.session.state != "starting":
            return
        if self.probe and self.probe.isRunning():
            QTimer.singleShot(30, self.start_upgrade)
            return
        if self.worker and self.worker.isRunning():
            QTimer.singleShot(30, self.start_upgrade)
            return
        if not self.session.begin():
            return
        self.busy = True
        self.timer.stop()
        self._last_log_bucket = None
        self.progress_bar.setValue(0)
        self.message.setText("正在检查设备并进入 Boot…")
        self.note.setText("正在烧录，请勿断电、拔出 USB 或关闭程序。")
        self.append_log("开始第 %d 次烧录。" % (self.session.succeeded + self.session.failed + 1))
        for helper in self.help_buttons:
            helper.setEnabled(False)
        self.refresh_action()
        if self.worker:
            self.worker.deleteLater()
        self.worker = UpgradeWorker(self.package, self)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.upgrade_finished)
        self.worker.start()

    def update_progress(self, value, text):
        self.progress_bar.setValue(value)
        self.message.setText(text)
        bucket = value // 10
        if value < 12 or value >= 94 or bucket != self._last_log_bucket:
            self.append_log(text)
            self._last_log_bucket = bucket

    def upgrade_finished(self):
        if self.worker.isRunning():
            QTimer.singleShot(30, self.upgrade_finished)
            return
        self.show_outcome(self.worker.outcome, self.worker.error)

    def show_outcome(self, outcome=None, error=""):
        self.busy = False
        self.session.complete(outcome, error)
        self.counts.setText("成功 %d   /   失败 %d" % (self.session.succeeded, self.session.failed))
        for helper in self.help_buttons:
            helper.setEnabled(True)
        if error:
            self.message.setText("烧录未完成，请检查连接")
            self.connection.setText(error)
            self.note.setText("不会自动关闭或重复烧录。可检查后重试，或拔下本把并更换下一把。")
            self.append_log("烧录失败：" + error)
            self.log.show()
            self.log_toggle.setText("收起升级日志")
        elif not outcome or not outcome.reconnected:
            self.message.setText("写入和校验完成，尚未确认退出 DFU 后的连接")
            self.connection.setText(outcome.message if outcome else "未收到完整的升级结果。")
            self.note.setText("请检查键盘是否恢复工作；确认连接前不开始关闭倒计时。")
            self.append_log(self.connection.text())
        else:
            self.progress_bar.setValue(100)
            self.message.setText("烧录成功 · 已退出 DFU 并重新连接")
            self.connection.setText(outcome.message)
            self.append_log("烧录成功，读回校验通过，设备已退出 DFU 并重新连接。")
            if self.session.continuous:
                self.note.setText("请拔下已完成的键盘，等待提示后连接下一把。程序将继续自动烧录。")
            else:
                self.countdown_tick()
                if not self.safe_preview:
                    self.countdown_timer.start()
        self.refresh_action()
        if self.session.state != "countdown" and not self.safe_preview:
            self.timer.start()

    def countdown_tick(self):
        remaining = self.session.remaining()
        if remaining is None:
            return
        if remaining <= 0:
            self.session.state = "done"
            self.countdown_timer.stop()
            self.close()
        else:
            self.note.setText("升级成功，键盘已退出 DFU。%d 秒后自动关闭程序。" % remaining)
            self.start_button.setText("升级完成 · %d 秒后自动关闭" % remaining)

    def refresh_action(self):
        state = self.session.state
        if self.busy or state in ("starting", "flashing"):
            self.start_button.setEnabled(False)
            self.start_button.setText("正在烧录，请勿断电…")
        elif state == "countdown":
            self.start_button.setEnabled(False)
            self.start_button.setText("升级完成 · %d 秒后自动关闭" % self.session.remaining())
        elif state in ("failed", "warning"):
            self.start_button.setEnabled(not self.safe_preview)
            self.start_button.setText("检查后重新检测并重试")
        elif not self.session.enabled:
            self.start_button.setEnabled(not self.safe_preview)
            self.start_button.setText("开始连续烧录" if self.session.continuous else "开始升级")
        elif self.session.continuous:
            self.start_button.setEnabled(not self.safe_preview)
            self.start_button.setText("继续自动烧录" if self.session.paused else "暂停自动烧录")
        else:
            self.start_button.setEnabled(False)
            self.start_button.setText("正在等待设备连接…")

    def action_clicked(self):
        if self.safe_preview or self.busy:
            return
        if self.session.retry():
            self.append_log("手动重新检测；识别到匹配设备后自动重试。")
            self.probe_device()
        elif not self.session.enabled and self.session.activate():
            self.append_log("已点击开始，等待匹配键盘并进行烧录。")
            self.probe_device()
        elif self.session.continuous:
            self.session.paused = not self.session.paused
            if self.session.state == "starting":
                self.session.state = "waiting"
            self.append_log("自动烧录已暂停。" if self.session.paused else "自动烧录已恢复。")
            if not self.session.paused:
                self.probe_device()
        self.refresh_action()

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出烧录日志", "qmk-upgrade.log", "日志 (*.log)")
        if path:
            Path(path).write_text("\n".join(self.log_lines) + "\n", encoding="utf-8")

    def toggle_log(self):
        show = self.log.isHidden()
        self.log.setVisible(show)
        self.log_toggle.setText("收起升级日志" if show else "查看升级日志")

    def closeEvent(self, event):
        if self.busy or (self.worker and self.worker.isRunning()):
            self.note.setText("正在烧录，请等待写入、校验和退出 DFU 完成。")
            event.ignore()
            return
        self._closing = True
        self.timer.stop()
        self.countdown_timer.stop()
        if self.probe and self.probe.isRunning():
            if not self._probe_close_connected:
                self.probe.finished.connect(self.close)
                self._probe_close_connected = True
            event.ignore()
        else:
            event.accept()
