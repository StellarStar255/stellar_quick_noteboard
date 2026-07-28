"""Pure-logic persistence layer for Quick Note Board (no Qt/Tk imports).

Ported from QuickNoteBoard.py (v1). CRITICAL: every on-disk format here is
byte/semantics-compatible with v1 — v1 and v2 open the same data directory.

Data-directory layout (all paths relative to ``data_dir``)::

    notebooks/<name>/notes.txt                    per-notebook note text
    notebooks/<name>/attachments/                 pasted images / files
    notebooks/<name>/attachments/filename_map.json  internal name -> original
    backups/<name>_backup_%Y%m%d_%H%M%S.txt       automatic backups (keep 10)
    config.json                                   app configuration
    notebook_order.json                           {"order": [...], "shortcuts": [...]}
                                                  (legacy: bare list == order only)
    history.txt                                   recycled snippets, newest first
    history.json                                  legacy history (migrated once)
    url_titles_cache.json                         URL -> page title cache

Config keys (v1 ``load_config``/``save_config``) — all 18 keys and defaults:

    ==================  ==============  =========================================
    Key                 v1 default      Meaning
    ==================  ==============  =========================================
    always_on_top       False           keep window topmost
    font_size           12              note text font size
    image_width         400             max width for pasted images
    icon_size           24              file-link icon font size
    ui_font_size        (auto)          UI font size; when absent v1 keeps the
                                        platform-detected size (no fixed default)
    text_padding        10              editor horizontal padding (px)
    show_image_name     True            show filename under pasted images
    geometry            (none)          Tk geometry string "WxH+X+Y"; only
                                        applied when present
    current_notebook    "默认"          notebook restored on startup (falls back
                                        to first existing notebook)
    sidebar_visible     True            notebook sidebar shown
    sidebar_width       150             sidebar width (px)
    show_recycle_box    True            recycle box shown
    theme               "dark"          theme name (validated against THEMES)
    outline_width       240             TOC panel width (px)
    outline_height      0               TOC panel height (0 = auto)
    outline_font_size   12              TOC font size
    outline_visible     False           TOC panel restored open
    language            "zh"            UI language, "zh" or "en"
    ==================  ==============  =========================================

``config.json`` is written by v1 with plain ``json.dumps`` (default kwargs:
ASCII-escaped, no indent) — mirrored here byte-for-byte.

NoteStore is a thin persistence facade: defaults/validation of config values
belong to the app layer. ``load_config``/``save_config`` are dict passthrough
and preserve unknown keys.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import NamedTuple


# ── Atomic write helpers ───────────────────────────────────────────────
# Copied verbatim from QuickNoteBoard.py (L128–156); they mirror
# noteboard.core.paths.atomic_write_text/atomic_write_json. Kept as local
# private helpers so this module has zero cross-module dependencies.

def _atomic_write_text(path, content):
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


def _atomic_write_json(path, data, **dump_kwargs):
    """Atomically serialize *data* as JSON to *path* (see _atomic_write_text)."""
    _atomic_write_text(path, json.dumps(data, **dump_kwargs))


# ── Config keys (documented in module docstring) ───────────────────────
# ``ui_font_size`` and ``geometry`` have no fixed v1 default: when absent,
# v1 keeps the auto-detected UI size / current window geometry. They are
# recorded as None here.
CONFIG_KEYS = {
    "always_on_top": False,
    "font_size": 12,
    "image_width": 400,
    "icon_size": 24,
    "ui_font_size": None,
    "text_padding": 10,
    "show_image_name": True,
    "geometry": None,
    "current_notebook": "默认",
    "sidebar_visible": True,
    "sidebar_width": 150,
    "show_recycle_box": True,
    "theme": "dark",
    "outline_width": 240,
    "outline_height": 0,
    "outline_font_size": 12,
    "outline_visible": False,
    "language": "zh",
}


class BackupInfo(NamedTuple):
    """One automatic backup: filename (within backups/), parsed timestamp
    (None when the stamp does not parse — v1 shows the raw stamp then),
    and file size in bytes."""
    filename: str
    timestamp: datetime | None
    size: int


class NoteStore:
    """All paths relative to *data_dir* (the v1 app chdirs there; pass an
    explicit directory in tests)."""

    NOTEBOOKS_DIR = "notebooks"
    NOTE_FILE = "notes.txt"
    ATTACHMENTS_DIR = "attachments"
    BACKUPS_DIR = "backups"
    CONFIG_FILE = "config.json"
    ORDER_FILE = "notebook_order.json"
    HISTORY_FILE = "history.txt"
    LEGACY_HISTORY_FILE = "history.json"
    URL_TITLE_CACHE_FILE = "url_titles_cache.json"
    DEFAULT_NOTEBOOK = "默认"
    BACKUP_KEEP = 10

    def __init__(self, data_dir: str = "."):
        self.data_dir = data_dir

    def _p(self, *parts: str) -> str:
        return os.path.join(self.data_dir, *parts)

    # ── Notebooks ──────────────────────────────────────────────────────

    def ensure_notebooks_dir(self) -> None:
        """Create notebooks/ if missing; create the default notebook only
        when NO notebook exists at all (the user may have deliberately
        deleted "默认"), migrating old root-level data into it."""
        notebooks_dir = self._p(self.NOTEBOOKS_DIR)
        if not os.path.exists(notebooks_dir):
            os.makedirs(notebooks_dir)
        has_any = any(os.path.isdir(os.path.join(notebooks_dir, n))
                      for n in os.listdir(notebooks_dir))
        if not has_any:
            default_path = os.path.join(notebooks_dir, self.DEFAULT_NOTEBOOK)
            os.makedirs(default_path)
            self._migrate_old_data(default_path)

    def _migrate_old_data(self, default_path: str) -> None:
        """Migrate v0 root-level notes.txt and attachments/ into the
        default notebook (port of v1 migrate_old_data)."""
        old_notes = self._p("notes.txt")
        if os.path.exists(old_notes):
            try:
                shutil.move(old_notes, os.path.join(default_path, self.NOTE_FILE))
            except OSError as e:
                print(f"Error migrating notes.txt: {e}")

        old_attachments = self._p("attachments")
        if os.path.exists(old_attachments) and os.path.isdir(old_attachments):
            try:
                shutil.move(old_attachments,
                            os.path.join(default_path, self.ATTACHMENTS_DIR))
            except OSError as e:
                print(f"Error migrating attachments: {e}")

    def list_notebooks(self) -> list[str]:
        """Raw sorted directory listing (no order/shortcut logic applied)."""
        notebooks_dir = self._p(self.NOTEBOOKS_DIR)
        notebooks = []
        if os.path.exists(notebooks_dir):
            for name in os.listdir(notebooks_dir):
                path = os.path.join(notebooks_dir, name)
                if os.path.isdir(path) and not name.startswith('.'):
                    notebooks.append(name)
        return sorted(notebooks)

    def ordered_notebooks(self) -> list[str]:
        """Notebook list exactly as v1 get_notebooks_list orders it:
        shortcuts first (in their saved order), then the rest by most
        recently modified note file (newest first), name as tiebreaker.

        Note: like v1, the saved "order" list is NOT used for sorting here —
        only "shortcuts" affects the result."""
        notebooks = self.list_notebooks()
        _order, shortcuts = self.load_order()
        shortcuts_set = set(shortcuts)
        notebooks_dir = self._p(self.NOTEBOOKS_DIR)

        def get_notebook_mtime(name):
            note_path = os.path.join(notebooks_dir, name, self.NOTE_FILE)
            try:
                return os.path.getmtime(note_path)
            except OSError:
                try:
                    return os.path.getmtime(os.path.join(notebooks_dir, name))
                except OSError:
                    return 0

        def sort_key(name):
            if name in shortcuts_set:
                return (0, shortcuts.index(name), 0, name)
            return (1, -get_notebook_mtime(name), 0, name)

        return sorted(notebooks, key=sort_key)

    def notebook_path(self, nb: str) -> str:
        return self._p(self.NOTEBOOKS_DIR, nb)

    def note_path(self, nb: str) -> str:
        return os.path.join(self.notebook_path(nb), self.NOTE_FILE)

    def attachments_path(self, nb: str) -> str:
        return os.path.join(self.notebook_path(nb), self.ATTACHMENTS_DIR)

    def ensure_attachments_dir(self, nb: str) -> None:
        attachments_path = self.attachments_path(nb)
        if not os.path.exists(attachments_path):
            os.makedirs(attachments_path)

    def create_notebook(self, name: str) -> None:
        """Create a notebook directory (with its attachments/ subdir).

        Raises ValueError on an empty name or a duplicate — the same rules
        v1 create_notebook enforces before creating."""
        if not name:
            raise ValueError("Notebook name cannot be empty")
        if name in self.list_notebooks():
            raise ValueError(f"Notebook already exists: {name}")
        notebook_path = self.notebook_path(name)
        os.makedirs(notebook_path)
        os.makedirs(os.path.join(notebook_path, self.ATTACHMENTS_DIR))

    def rename_notebook(self, old: str, new: str) -> None:
        """Rename a notebook directory. Raises ValueError on empty target
        name or duplicate (v1 do_rename rules; the "默认 cannot be renamed"
        rule is app-layer policy, not enforced here)."""
        if not new:
            raise ValueError("Notebook name cannot be empty")
        if new == old:
            return
        if new in self.list_notebooks():
            raise ValueError(f"Notebook already exists: {new}")
        os.rename(self.notebook_path(old), self.notebook_path(new))

    def delete_notebook(self, name: str) -> None:
        """Delete a notebook directory tree (v1's "cannot delete the last
        notebook" rule is app-layer policy, not enforced here)."""
        shutil.rmtree(self.notebook_path(name))

    # ── Notes ──────────────────────────────────────────────────────────

    def load_note_text(self, nb: str) -> str:
        note_path = self.note_path(nb)
        if os.path.exists(note_path):
            with open(note_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def save_note_text(self, nb: str, text: str) -> None:
        """Atomically write the note file.

        Data-loss guard (as in v1 save_notes): never overwrite a note that
        has real content on disk with empty/whitespace-only content — the
        on-disk content is left untouched in that case."""
        note_path = self.note_path(nb)
        if not text.strip():
            try:
                if os.path.exists(note_path) and os.path.getsize(note_path) > 0:
                    with open(note_path, "r", encoding="utf-8") as f:
                        existing = f.read()
                    if existing.strip():
                        print(f"save_note_text: refused to overwrite non-empty "
                              f"note '{nb}' with empty content "
                              f"(skipped to prevent data loss).")
                        return
            except OSError as e:
                print(f"save_note_text empty-guard error: {e}")
        _atomic_write_text(note_path, text)

    # ── Backups ────────────────────────────────────────────────────────

    def backup_note(self, nb: str, content: str | None) -> str | None:
        """Write ``backups/{nb}_backup_%Y%m%d_%H%M%S.txt`` with *content*
        and prune old backups for this notebook to the newest 10.

        Runs synchronously (v1 threads this; the caller may too). When
        *content* is None, the current on-disk note is snapshotted instead
        (v1 behaviour); returns None if there is nothing to back up."""
        if content is None:
            note_path = self.note_path(nb)
            if not os.path.exists(note_path):
                return None
            try:
                with open(note_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except OSError as e:
                print(f"Error reading notes for backup: {e}")
                return None

        backup_dir = self._p(self.BACKUPS_DIR)
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"{nb}_backup_{timestamp}.txt")
        _atomic_write_text(backup_file, content)

        # Clean old backups for this notebook, keep only last 10
        prefix = f"{nb}_backup_"
        backups = sorted(f for f in os.listdir(backup_dir)
                         if f.startswith(prefix))
        while len(backups) > self.BACKUP_KEEP:
            try:
                os.remove(os.path.join(backup_dir, backups.pop(0)))
            except FileNotFoundError:
                pass  # a concurrent prune already removed it
        return backup_file

    def list_backups(self, nb: str) -> list[BackupInfo]:
        """Backups for *nb*, newest first (exactly how v1's restore dialog
        lists them: prefix+".txt" filter, reverse filename sort, timestamp
        parsed from the filename stamp — None when it does not parse)."""
        backup_dir = self._p(self.BACKUPS_DIR)
        prefix = f"{nb}_backup_"
        try:
            files = sorted(
                (f for f in os.listdir(backup_dir)
                 if f.startswith(prefix) and f.endswith(".txt")),
                reverse=True)
        except FileNotFoundError:
            return []

        result = []
        for fname in files:
            stamp = fname[len(prefix):-4]
            try:
                ts = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
            except ValueError:
                ts = None
            try:
                size = os.path.getsize(os.path.join(backup_dir, fname))
            except OSError:
                size = 0
            result.append(BackupInfo(fname, ts, size))
        return result

    def read_backup(self, filename: str) -> str:
        with open(os.path.join(self._p(self.BACKUPS_DIR), filename),
                  "r", encoding="utf-8") as f:
            return f.read()

    # ── Notebook order & shortcuts (pins) ──────────────────────────────

    def load_order(self) -> tuple[list[str], list[str]]:
        """Return (order, shortcuts) from notebook_order.json.

        Supports both formats exactly like v1: legacy bare list (order only,
        no shortcuts) and current {"order": [...], "shortcuts": [...]}.
        Missing or unreadable file yields ([], [])."""
        order_file = self._p(self.ORDER_FILE)
        if os.path.exists(order_file):
            try:
                with open(order_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data, []
                return data.get("order", []), data.get("shortcuts", [])
            except Exception as e:
                print(f"Error loading notebook order: {e}")
                return [], []
        return [], []

    def save_order(self, order: list[str], shortcuts: list[str]) -> None:
        data = {"order": order, "shortcuts": shortcuts}
        _atomic_write_json(self._p(self.ORDER_FILE), data,
                           ensure_ascii=False, indent=2)

    # ── Config (thin dict passthrough) ─────────────────────────────────

    def load_config(self) -> dict:
        """Raw config dict ({} when missing/unreadable). Interpretation of
        keys and defaults belongs to the app layer (see CONFIG_KEYS)."""
        config_file = self._p(self.CONFIG_FILE)
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}")
        return {}

    def save_config(self, cfg: dict) -> None:
        """Atomic write with v1's exact serialization: plain json.dumps
        (default kwargs — ASCII-escaped, no indent)."""
        _atomic_write_json(self._p(self.CONFIG_FILE), cfg)

    # ── Filename map (per notebook) ────────────────────────────────────

    def _filename_map_path(self, nb: str) -> str:
        return os.path.join(self.attachments_path(nb), "filename_map.json")

    def load_filename_map(self, nb: str) -> dict:
        """attachments/filename_map.json: internal filename -> either
        {"name": original_name, "path": original_path} or a bare string
        (legacy format, original name only). Returned as-is."""
        map_file = self._filename_map_path(nb)
        if os.path.exists(map_file):
            try:
                with open(map_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading filename map: {e}")
        return {}

    def save_filename_map(self, nb: str, mapping: dict) -> None:
        _atomic_write_json(self._filename_map_path(nb), mapping,
                           ensure_ascii=False, indent=2)

    @staticmethod
    def display_name(mapping: dict, internal_name: str) -> str:
        """Original filename for display (v1 get_display_name): dict entry
        -> "name", legacy string entry -> itself, missing -> internal name."""
        info = mapping.get(internal_name)
        if isinstance(info, dict):
            return info.get("name", internal_name)
        elif isinstance(info, str):
            return info  # legacy format
        return internal_name

    @staticmethod
    def original_path(mapping: dict, internal_name: str) -> str | None:
        """Original file path (v1 get_original_path); None for legacy or
        missing entries."""
        info = mapping.get(internal_name)
        if isinstance(info, dict):
            return info.get("path")
        return None

    # ── History (recycled snippets) ────────────────────────────────────

    def append_history(self, text: str, timestamp: str) -> None:
        """Prepend one entry to history.txt in v1's exact format:
        ``--- {timestamp} ---\\n{text}\\n\\n`` followed by the existing
        content (newest entries first)."""
        new_entry = f"--- {timestamp} ---\n{text}\n\n"
        existing_content = self.read_history()
        _atomic_write_text(self._p(self.HISTORY_FILE),
                           new_entry + existing_content)

    def read_history(self) -> str:
        history_file = self._p(self.HISTORY_FILE)
        if os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError as e:
                print(f"Error reading history: {e}")
        return ""

    def write_history(self, content: str) -> None:
        _atomic_write_text(self._p(self.HISTORY_FILE), content)

    def migrate_legacy_history(self) -> None:
        """One-time migration of legacy history.json into history.txt
        (only when the txt does not exist yet; the json is kept, as in v1)."""
        json_file = self._p(self.LEGACY_HISTORY_FILE)
        txt_file = self._p(self.HISTORY_FILE)
        if os.path.exists(json_file) and not os.path.exists(txt_file):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    history_data = json.load(f)
                migrated = "".join(
                    f"--- {item['timestamp']} ---\n{item['content']}\n\n"
                    for item in history_data)
                _atomic_write_text(txt_file, migrated)
            except Exception as e:
                print(f"Error migrating history: {e}")

    # ── URL title cache ────────────────────────────────────────────────
    # v1 stores this next to the script file (__file__ dir == the data dir
    # when running from source); the store keeps it in data_dir.

    def load_url_title_cache(self) -> dict:
        cache_file = self._p(self.URL_TITLE_CACHE_FILE)
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_url_title_cache(self, cache: dict) -> None:
        try:
            _atomic_write_json(self._p(self.URL_TITLE_CACHE_FILE), cache,
                               ensure_ascii=False, indent=2)
        except Exception:
            pass  # cache write failure is non-fatal (v1 behaviour)
