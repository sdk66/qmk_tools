"""Single/customer and continuous/factory lifecycle, with no USB or Qt I/O."""
import math
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    apps: int = 0
    targets: int = 0
    boots: int = 0
    product: str = ""

    @property
    def empty(self):
        return not (self.apps or self.targets or self.boots)


class BurnSession:
    CLOSE_DELAY = 5
    REMOVAL_SETTLE = 0.6

    def __init__(self, settings, clock=time.monotonic):
        settings.validate()
        self.settings = settings
        self.clock = clock
        self.state = "waiting"
        self.paused = False
        self.enabled = settings.auto_start
        self.succeeded = 0
        self.failed = 0
        self.empty_since = None
        self.close_deadline = None
        self.same_identity = ((settings.app_vid, settings.app_pid, settings.usage_page, settings.usage_id) ==
                              (settings.target_vid, settings.target_pid, settings.target_usage_page, settings.target_usage_id))

    @property
    def continuous(self):
        return self.settings.burn_mode == "continuous"

    def observe(self, detection):
        if self.state in ("starting", "flashing", "countdown", "done"):
            return "idle"
        if self.state in ("remove", "failed", "warning"):
            # Monitor APP, the NEW firmware's APP, and Boot. USB re-enumeration
            # or an APP VID/PID change must never immediately re-arm a station.
            if detection.empty:
                if self.empty_since is None:
                    self.empty_since = self.clock()
                elif self.clock() - self.empty_since >= self.REMOVAL_SETTLE:
                    self.empty_since = None
                    self.state = "waiting"
                    return "next"
            else:
                self.empty_since = None
            return "remove" if self.state == "remove" else "blocked"
        if self.paused:
            return "paused"
        if (detection.apps > 1 or detection.boots > 1 or detection.targets > 1
                or (detection.apps and detection.boots) or (detection.targets and detection.boots)
                or (not self.same_identity and detection.apps and detection.targets)):
            return "multiple"
        if detection.apps == 1 or (detection.boots == 1 and self.settings.allow_boot_recovery):
            if not self.enabled:
                return "ready"
            self.state = "starting"
            return "start"
        if detection.boots:
            return "boot_blocked"
        return "waiting"

    def begin(self):
        if self.state != "starting" or not self.enabled:
            return False
        self.state = "flashing"
        return True

    def complete(self, outcome=None, error=""):
        self.empty_since = None
        if not self.continuous:
            self.enabled = self.settings.auto_start
        if error:
            self.failed += 1
            self.state = "failed"
        elif outcome is None or not outcome.reconnected:
            # Successful read-back alone cannot start an auto-close timer.
            self.failed += 1
            self.state = "warning"
        else:
            self.succeeded += 1
            if self.continuous:
                self.state = "remove"
            else:
                self.state = "countdown"
                self.close_deadline = self.clock() + self.CLOSE_DELAY

    def remaining(self):
        if self.state != "countdown":
            return None
        return max(0, int(math.ceil(self.close_deadline - self.clock())))

    def retry(self):
        if self.state in ("failed", "warning"):
            self.empty_since = None
            self.state = "waiting"
            self.enabled = True
            self.paused = False
            return True
        return False

    def activate(self):
        if self.state != "waiting":
            return False
        self.enabled = True
        self.paused = False
        return True
