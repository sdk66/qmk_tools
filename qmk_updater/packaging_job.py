"""Build customer packages without blocking the maker's event loop."""
import time

from .qt import QThread, Signal
from .runtimes import system_package


class PackagingWorker(QThread):
    progress = Signal(int, str)

    def __init__(self, template, destination, data, target, parent=None):
        super().__init__(parent)
        self.template, self.destination = template, destination
        self.data, self.target = data, target
        self.error = ""
        self.elapsed = 0
        self._last_progress = None

    def report(self, value, message):
        current = (max(0, min(100, int(value))), message)
        if current != self._last_progress:
            self._last_progress = current
            self.progress.emit(*current)

    def run(self):
        started = time.monotonic()
        try:
            system_package(self.template, self.destination, self.data, self.target,
                           progress=self.report)
        except Exception as error:
            self.error = str(error) or type(error).__name__
        finally:
            self.elapsed = time.monotonic() - started
