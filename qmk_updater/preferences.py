"""Small, maker-only preferences for file dialog locations.

No settings are created merely by opening the maker. Customer upgrade packages
do not need this module or its per-user settings file.
"""
import json
import os
from pathlib import Path
import sys
import tempfile


_APP_DIRECTORY = "QMK-Firmware-Studio"
_DIRECTORY_KINDS = frozenset(("firmware", "output", "template", "project"))


def default_preferences_path():
    """Return the maker settings path without creating directories or files."""
    override = os.environ.get("QMK_PREFERENCES_PATH")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return base / _APP_DIRECTORY / "preferences.json"


def _existing_parent(path):
    """Find an existing directory, including when a saved folder was removed."""
    try:
        candidate = Path(path).expanduser().absolute()
        for directory in (candidate,) + tuple(candidate.parents):
            try:
                if directory.is_dir():
                    return directory
            except OSError:
                continue
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return None


class MakerPreferences:
    """Remember independent input/output directories across maker launches.

    ``path`` and ``fallback_directory`` can be injected by tests or a portable
    maker. Loading and saving failures leave the maker usable. ``directory``
    returns a string suitable for Qt file dialogs; ``remember_file`` accepts a
    selected filename and returns whether the preferences were saved to disk.
    """

    def __init__(self, path=None, fallback_directory=None):
        self.path = Path(path).expanduser() if path is not None else default_preferences_path()
        self._fallback_directory = fallback_directory
        self._directories = {}
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
            directories = data.get("directories", {}) if isinstance(data, dict) else {}
            if isinstance(directories, dict):
                for kind, value in directories.items():
                    if (kind in _DIRECTORY_KINDS and isinstance(value, str)
                            and value and "\x00" not in value and Path(value).is_absolute()):
                        self._directories[kind] = value
        except (OSError, UnicodeError, ValueError):
            pass

    def directory(self, kind):
        """Return this dialog's saved directory, or a usable default folder."""
        self._check_kind(kind)
        saved = self._directories.get(kind)
        if saved:
            directory = _existing_parent(saved)
            if directory is not None:
                return str(directory)
        if self._fallback_directory is not None:
            directory = _existing_parent(self._fallback_directory)
            if directory is not None:
                return str(directory)
        try:
            home = Path.home()
            for candidate in (home / "Documents", home):
                if candidate.is_dir():
                    return str(candidate)
        except (OSError, RuntimeError):
            pass
        return str(Path.cwd())

    def remember_file(self, kind, path):
        """Remember a selected file's parent; cancelled dialogs do not write."""
        self._check_kind(kind)
        if path is None:
            return False
        try:
            filename = os.fspath(path)
            if not isinstance(filename, str) or not filename.strip() or "\x00" in filename:
                return False
            directory = Path(filename).expanduser().absolute().parent
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
        self._directories[kind] = str(directory)
        return self._save()

    @staticmethod
    def _check_kind(kind):
        if kind not in _DIRECTORY_KINDS:
            raise ValueError("Unknown maker directory kind: " + str(kind))

    def _save(self):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=str(self.path.parent),
                    prefix=".preferences-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({"version": 1, "directories": self._directories}, stream,
                          ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(self.path))
            return True
        except (OSError, UnicodeError, ValueError):
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass
