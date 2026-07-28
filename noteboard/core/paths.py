"""Filesystem paths and atomic-write helpers (no GUI imports)."""

import json
import os
import platform
import sys


def resource_path(*parts):
    """Path to a bundled read-only resource, both from source and frozen.

    When frozen, PyInstaller unpacks resources under sys._MEIPASS. From
    source, assets/ lives at the repo root — the parent directory of the
    noteboard package (this file is noteboard/core/paths.py).
    """
    default_base = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    base = getattr(sys, "_MEIPASS", default_base)
    return os.path.join(base, *parts)


def user_data_dir():
    """Per-user writable data directory for the installed (frozen) app.

    Overridable via STELLAR_NOTEBOARD_DATA_DIR (used by tests and portable
    setups). When running from source the app keeps using the current
    working directory, matching the historical behaviour.
    """
    override = os.environ.get("STELLAR_NOTEBOARD_DATA_DIR")
    if override:
        return override
    home = os.path.expanduser("~")
    system = platform.system()
    if system == "Darwin":
        return os.path.join(home, "Library", "Application Support",
                            "StellarQuickNoteboard")
    if system == "Windows":
        return os.path.join(os.environ.get("APPDATA", home),
                            "StellarQuickNoteboard")
    xdg = os.environ.get("XDG_DATA_HOME",
                         os.path.join(home, ".local", "share"))
    return os.path.join(xdg, "stellar-quick-noteboard")


def atomic_write_text(path, content):
    """Write text to *path* atomically: write a temp file in the same
    directory, fsync, then os.replace. A crash mid-write can never leave a
    truncated/corrupt file behind — the old content survives intact."""
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def atomic_write_json(path, data, **dump_kwargs):
    """Atomically serialize *data* as JSON to *path* (see atomic_write_text)."""
    atomic_write_text(path, json.dumps(data, **dump_kwargs))
