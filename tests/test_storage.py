"""Tests for noteboard.core.storage and noteboard.core.attachments.

Pure pytest + tmp_path — no Qt/Tk, never touches the repo's live data
directory (notebooks/, backups/, config.json are the user's real data).
"""

import json
import os
import time
from datetime import datetime

import pytest

from noteboard.core import attachments
from noteboard.core.storage import CONFIG_KEYS, BackupInfo, NoteStore


@pytest.fixture
def store(tmp_path):
    return NoteStore(str(tmp_path))


# ── Notebook CRUD ──────────────────────────────────────────────────────

def test_ensure_notebooks_dir_creates_default_only_when_empty(store, tmp_path):
    store.ensure_notebooks_dir()
    assert (tmp_path / "notebooks" / "默认").is_dir()

    # Delete 默认, create another notebook: 默认 must NOT come back
    store.delete_notebook("默认")
    store.create_notebook("work")
    store.ensure_notebooks_dir()
    assert store.list_notebooks() == ["work"]


def test_ensure_notebooks_dir_migrates_old_root_data(store, tmp_path):
    # v0 layout: notes.txt and attachments/ in the data dir root
    (tmp_path / "notes.txt").write_text("old note", encoding="utf-8")
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "pic.png").write_bytes(b"png")

    store.ensure_notebooks_dir()

    default = tmp_path / "notebooks" / "默认"
    assert (default / "notes.txt").read_text(encoding="utf-8") == "old note"
    assert (default / "attachments" / "pic.png").exists()
    assert not (tmp_path / "notes.txt").exists()
    assert not (tmp_path / "attachments").exists()


def test_create_notebook_makes_attachments_dir(store, tmp_path):
    store.create_notebook("nb1")
    assert (tmp_path / "notebooks" / "nb1" / "attachments").is_dir()
    assert store.list_notebooks() == ["nb1"]


def test_create_notebook_rejects_duplicate_and_empty(store):
    store.create_notebook("nb1")
    with pytest.raises(ValueError):
        store.create_notebook("nb1")
    with pytest.raises(ValueError):
        store.create_notebook("")


def test_rename_notebook(store, tmp_path):
    store.create_notebook("old")
    store.save_note_text("old", "hello")
    store.rename_notebook("old", "new")
    assert store.list_notebooks() == ["new"]
    assert store.load_note_text("new") == "hello"


def test_rename_notebook_rejects_duplicate_and_empty(store):
    store.create_notebook("a")
    store.create_notebook("b")
    with pytest.raises(ValueError):
        store.rename_notebook("a", "b")
    with pytest.raises(ValueError):
        store.rename_notebook("a", "")
    # Renaming to the same name is a no-op (v1 behaviour)
    store.rename_notebook("a", "a")
    assert sorted(store.list_notebooks()) == ["a", "b"]


def test_delete_notebook(store):
    store.create_notebook("gone")
    store.create_notebook("kept")
    store.delete_notebook("gone")
    assert store.list_notebooks() == ["kept"]


def test_list_notebooks_skips_hidden_and_files(store, tmp_path):
    store.create_notebook("visible")
    (tmp_path / "notebooks" / ".hidden").mkdir()
    (tmp_path / "notebooks" / "stray.txt").write_text("x", encoding="utf-8")
    assert store.list_notebooks() == ["visible"]


# ── Notes ──────────────────────────────────────────────────────────────

def test_note_text_roundtrip(store):
    store.create_notebook("nb")
    store.save_note_text("nb", "line1\nline2\n")
    assert store.load_note_text("nb") == "line1\nline2\n"
    assert store.load_note_text("missing") == ""


def test_save_note_text_refuses_blanking_nonempty_note(store):
    store.create_notebook("nb")
    store.save_note_text("nb", "real content")
    store.save_note_text("nb", "   \n  ")  # data-loss guard: must be a no-op
    assert store.load_note_text("nb") == "real content"


# ── Notebook order & shortcuts ─────────────────────────────────────────

def test_order_roundtrip(store, tmp_path):
    store.save_order(["a", "b"], ["b"])
    assert store.load_order() == (["a", "b"], ["b"])
    # On-disk format matches v1: {"order": [...], "shortcuts": [...]}
    data = json.loads((tmp_path / "notebook_order.json").read_text("utf-8"))
    assert data == {"order": ["a", "b"], "shortcuts": ["b"]}


def test_order_legacy_list_format(store, tmp_path):
    (tmp_path / "notebook_order.json").write_text(
        json.dumps(["x", "y"]), encoding="utf-8")
    assert store.load_order() == (["x", "y"], [])


def test_order_missing_and_corrupt(store, tmp_path):
    assert store.load_order() == ([], [])
    (tmp_path / "notebook_order.json").write_text("{not json", encoding="utf-8")
    assert store.load_order() == ([], [])


def test_ordered_notebooks_shortcuts_first_then_mtime(store):
    for name in ("aaa", "bbb", "ccc"):
        store.create_notebook(name)
        store.save_note_text(name, f"note {name}")
    now = time.time()
    # aaa oldest, bbb newest
    os.utime(store.note_path("aaa"), (now - 300, now - 300))
    os.utime(store.note_path("bbb"), (now - 10, now - 10))
    os.utime(store.note_path("ccc"), (now - 100, now - 100))
    store.save_order([], ["ccc"])  # ccc pinned

    # Pinned first, then newest-modified first
    assert store.ordered_notebooks() == ["ccc", "bbb", "aaa"]


# ── Backups ────────────────────────────────────────────────────────────

def test_backup_naming_pattern(store, tmp_path):
    store.create_notebook("nb")
    path = store.backup_note("nb", "content v1")
    fname = os.path.basename(path)
    assert fname.startswith("nb_backup_") and fname.endswith(".txt")
    stamp = fname[len("nb_backup_"):-4]
    datetime.strptime(stamp, "%Y%m%d_%H%M%S")  # must parse
    assert (tmp_path / "backups" / fname).read_text("utf-8") == "content v1"
    assert store.read_backup(fname) == "content v1"


def test_backup_keep_10_prune(store, tmp_path):
    store.create_notebook("nb")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # 12 pre-existing backups with older timestamps
    old = [f"nb_backup_2024010{1 + i // 10}_00000{i % 10}.txt" for i in range(12)]
    for f in old:
        (backup_dir / f).write_text("old", encoding="utf-8")
    # Backups of other notebooks are untouched by the prune
    (backup_dir / "other_backup_20240101_000000.txt").write_text("x", "utf-8")

    store.backup_note("nb", "newest")

    remaining = sorted(f for f in os.listdir(backup_dir)
                       if f.startswith("nb_backup_"))
    assert len(remaining) == 10  # 13 -> keep only last 10
    # The three oldest were pruned, the new backup survives
    assert remaining[:9] == sorted(old)[3:]
    assert (backup_dir / "other_backup_20240101_000000.txt").exists()


def test_list_backups_newest_first(store, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "nb_backup_20240101_120000.txt").write_text("a", "utf-8")
    (backup_dir / "nb_backup_20250601_090000.txt").write_text("bb", "utf-8")
    (backup_dir / "nb_backup_badstamp.txt").write_text("c", "utf-8")
    (backup_dir / "other_backup_20250101_000000.txt").write_text("d", "utf-8")
    (backup_dir / "nb_backup_20240101_120000.json").write_text("e", "utf-8")

    infos = store.list_backups("nb")
    assert [b.filename for b in infos] == [
        "nb_backup_badstamp.txt",           # reverse filename sort, like v1
        "nb_backup_20250601_090000.txt",
        "nb_backup_20240101_120000.txt",
    ]
    assert infos[0].timestamp is None       # unparseable stamp
    assert infos[1].timestamp == datetime(2025, 6, 1, 9, 0, 0)
    assert infos[2].size == 1
    assert isinstance(infos[0], BackupInfo)


def test_list_backups_no_dir(store):
    assert store.list_backups("nb") == []


def test_backup_note_none_content_snapshots_disk(store):
    store.create_notebook("nb")
    assert store.backup_note("nb", None) is None  # no note file yet
    store.save_note_text("nb", "on disk")
    path = store.backup_note("nb", None)
    assert store.read_backup(os.path.basename(path)) == "on disk"


# ── History ────────────────────────────────────────────────────────────

def test_history_prepend_format(store):
    store.append_history("first snippet", "2026-07-28 10:00:00")
    store.append_history("second\nsnippet", "2026-07-28 11:00:00")
    assert store.read_history() == (
        "--- 2026-07-28 11:00:00 ---\nsecond\nsnippet\n\n"
        "--- 2026-07-28 10:00:00 ---\nfirst snippet\n\n"
    )
    store.write_history("edited")
    assert store.read_history() == "edited"


def test_migrate_legacy_history(store, tmp_path):
    legacy = [
        {"timestamp": "2024-01-01 08:00:00", "content": "one"},
        {"timestamp": "2024-01-02 09:00:00", "content": "two"},
    ]
    (tmp_path / "history.json").write_text(
        json.dumps(legacy), encoding="utf-8")
    store.migrate_legacy_history()
    assert store.read_history() == (
        "--- 2024-01-01 08:00:00 ---\none\n\n"
        "--- 2024-01-02 09:00:00 ---\ntwo\n\n"
    )
    # json is kept (v1 keeps it), and migration never overwrites existing txt
    assert (tmp_path / "history.json").exists()
    store.write_history("current")
    store.migrate_legacy_history()
    assert store.read_history() == "current"


# ── Config ─────────────────────────────────────────────────────────────

def test_config_roundtrip_preserves_unknown_keys(store):
    cfg = {"theme": "light", "font_size": 14, "some_future_key": [1, 2, 3]}
    store.save_config(cfg)
    assert store.load_config() == cfg


def test_config_missing_and_corrupt(store, tmp_path):
    assert store.load_config() == {}
    (tmp_path / "config.json").write_text("{oops", encoding="utf-8")
    assert store.load_config() == {}


def test_config_keys_match_v1_defaults(store):
    # All 18 keys v1 reads/writes, with v1's load_config defaults
    assert CONFIG_KEYS == {
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


# ── Filename map ───────────────────────────────────────────────────────

def test_filename_map_roundtrip(store, tmp_path):
    store.create_notebook("nb")
    mapping = {
        "file_123.pdf": {"name": "原始文档.pdf", "path": "/tmp/原始文档.pdf"},
        "img_1.png": "legacy_name.png",  # legacy string format
    }
    store.save_filename_map("nb", mapping)
    assert store.load_filename_map("nb") == mapping
    map_file = tmp_path / "notebooks" / "nb" / "attachments" / "filename_map.json"
    assert map_file.exists()
    # ensure_ascii=False like v1: CJK stays readable on disk
    assert "原始文档" in map_file.read_text(encoding="utf-8")

    assert NoteStore.display_name(mapping, "file_123.pdf") == "原始文档.pdf"
    assert NoteStore.display_name(mapping, "img_1.png") == "legacy_name.png"
    assert NoteStore.display_name(mapping, "unknown") == "unknown"
    assert NoteStore.original_path(mapping, "file_123.pdf") == "/tmp/原始文档.pdf"
    assert NoteStore.original_path(mapping, "img_1.png") is None


def test_filename_map_missing(store):
    store.create_notebook("nb")
    assert store.load_filename_map("nb") == {}


# ── URL title cache ────────────────────────────────────────────────────

def test_url_title_cache_roundtrip(store):
    assert store.load_url_title_cache() == {}
    cache = {"https://example.com": "Example Domain"}
    store.save_url_title_cache(cache)
    assert store.load_url_title_cache() == cache


# ── attachments module ─────────────────────────────────────────────────

def test_referenced_attachments_markers():
    content = (
        "hello [IMAGE:a.png:300] world\n"
        "[FILE:b.pdf]\n"
        "[IMAGE:c d.jpg]\n"
        "not a marker: IMAGE: nope, [IMAGE] neither, [FILE] no\n"
    )
    assert attachments.referenced_attachments(content) == \
        {"a.png", "b.pdf", "c d.jpg"}
    assert attachments.referenced_attachments("plain text") == set()


def test_is_video_file():
    assert attachments.is_video_file("movie.mp4")
    assert attachments.is_video_file("MOVIE.MOV")
    assert attachments.is_video_file("clip.webm")
    assert not attachments.is_video_file("song.mp3")
    assert not attachments.is_video_file("doc.pdf")
    assert not attachments.is_video_file("mp4")  # no extension


def test_file_icon_mapping():
    if attachments._IS_LINUX:
        pytest.skip("emoji icons are macOS/Windows only")
    assert attachments.file_icon("a.mp4") == "🎬"
    assert attachments.file_icon("a.mp3") == "🎵"
    assert attachments.file_icon("a.pdf") == "📕"
    assert attachments.file_icon("a.docx") == "📝"
    assert attachments.file_icon("a.csv") == "📊"
    assert attachments.file_icon("a.zip") == "📦"
    assert attachments.file_icon("a.py") == "💻"
    assert attachments.file_icon("a.md") == "📄"
    assert attachments.file_icon("a.png") == "🖼️"
    assert attachments.file_icon("a.dmg") == "⚙️"
    assert attachments.file_icon("a.xyz") == "📎"


def test_cleanup_unused(tmp_path):
    att = tmp_path / "attachments"
    att.mkdir()
    for name in ("kept.png", "unused.png", "video.mp4", "pinned.pdf",
                 "_thumb_video.mp4.png", "_thumb_unused2.mp4.png",
                 "unused2.mp4", "filename_map.json", ".DS_Store", "fresh.png"):
        (att / name).write_bytes(b"x")

    content = "[IMAGE:kept.png:200] and [FILE:video.mp4]"
    # Age everything past the fresh-file grace except fresh.png
    old = time.time() - 120
    for name in os.listdir(att):
        if name != "fresh.png":
            os.utime(att / name, (old, old))

    deleted = attachments.cleanup_unused(
        str(att), content, keep_thumbs_for={"pinned.pdf"})

    assert sorted(deleted) == ["unused.png", "unused2.mp4"]
    remaining = set(os.listdir(att))
    # Referenced, pinned, fresh, map, dot-files and referenced thumbs stay
    assert remaining == {"kept.png", "video.mp4", "pinned.pdf",
                         "_thumb_video.mp4.png", "filename_map.json",
                         ".DS_Store", "fresh.png"}
    # Deleted attachment's thumb cache was removed alongside it
    assert "_thumb_unused2.mp4.png" not in remaining


def test_cleanup_unused_missing_dir(tmp_path):
    assert attachments.cleanup_unused(str(tmp_path / "nope"), "x") == []
