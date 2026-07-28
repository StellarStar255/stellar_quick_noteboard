"""M7 platform integration: clipboard file/rich copy, INTERNAL link
copy/paste roundtrip, the full v1 image/file object context menus, and
the update flow (no network — fetch/download are monkeypatched).
Offscreen Qt via pytest-qt."""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QMimeData, QRectF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from noteboard.core import updater
from noteboard.core.version import APP_VERSION
from noteboard.core.storage import NoteStore
from noteboard.core.theme import THEMES
from noteboard.ui import platform_utils
from noteboard.ui.editor.document import MarkerDocument, OBJECT_CHAR
from noteboard.ui.editor.highlighter import MarkdownHighlighter
from noteboard.ui.editor.note_edit import (MARKER_MIME, NoteTextEdit,
                                           _ObjectHit)
from noteboard.ui.main_window import MainWindow
from noteboard.ui.update_dialog import UpdateFlow


@pytest.fixture
def workspace(qtbot, tmp_path):
    attach = tmp_path / "attachments"
    attach.mkdir()
    md = MarkerDocument(attachments_dir=str(attach))
    saved = {}

    def saver(internal, original=None, path=None):
        if original:
            saved[internal] = {"name": original, "path": path}

    md.attachment_saver = saver
    md.filename_map = saved
    hl = MarkdownHighlighter(md.document, THEMES["dark"])
    editor = NoteTextEdit(md, hl)
    qtbot.addWidget(editor)
    return editor, md, attach, saved


def _make_qimage(w=60, h=40, color="#336699"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def _paste_image(editor):
    """Paste a bitmap; returns the internal img_*.png name."""
    mime = QMimeData()
    mime.setImageData(_make_qimage())
    editor.insertFromMimeData(mime)
    m = re.search(r"\[IMAGE:([^:\]]+)\]", editor.marker_doc.serialize())
    assert m
    return m.group(1)


def _paste_file(editor, tmp_path, name="report.pdf"):
    """Import a real file through the paste path; returns internal name."""
    src = tmp_path / name
    src.write_bytes(b"%PDF-1.4 fake")
    mime = QMimeData()
    from PySide6.QtCore import QUrl
    mime.setUrls([QUrl.fromLocalFile(str(src))])
    editor.insertFromMimeData(mime)
    m = re.search(r"\[FILE:([^\]]+)\]", editor.marker_doc.serialize())
    assert m
    return m.group(1)


def _object_hit(editor, name, is_file):
    pos = editor.document().toPlainText().index(OBJECT_CHAR)
    scheme = "attachfile" if is_file else "attach"
    return _ObjectHit(pos, name, f"{scheme}://{name}", is_file,
                      QRectF(0, 0, 10, 10))


def _menu_items(menu):
    return [(a.text(), a.isEnabled()) for a in menu.actions()
            if not a.isSeparator()]


# ── platform_utils clipboard ─────────────────────────────────────────────

def test_copy_file_to_clipboard_sets_url_and_text(qtbot, tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hi")
    assert platform_utils.copy_file_to_clipboard(str(f))
    mime = QApplication.clipboard().mimeData()
    assert mime.hasUrls()
    assert mime.urls()[0].toLocalFile() == str(f)
    assert mime.text() == str(f)


def test_copy_missing_file_is_a_noop(qtbot, tmp_path):
    platform_utils.copy_text("sentinel")
    assert not platform_utils.copy_file_to_clipboard(
        str(tmp_path / "ghost.bin"))
    assert QApplication.clipboard().text() == "sentinel"


def test_copy_image_file_also_sets_bitmap(qtbot, tmp_path):
    f = tmp_path / "pic.png"
    _make_qimage().save(str(f))
    platform_utils.copy_file_to_clipboard(str(f))
    mime = QApplication.clipboard().mimeData()
    assert mime.hasUrls() and mime.hasImage()


def test_strikethrough_html_builder():
    html = platform_utils.strikethrough_html(
        "a [STRIKE]b<c[/STRIKE] [HL:green]d[/HL]\ne")
    assert '<s style="color:#888888">b&lt;c</s>' in html
    assert "[STRIKE]" not in html and "[HL:" not in html
    assert "<br>" in html


def test_rich_strikethrough_copy_sets_html_and_plain(qtbot, workspace):
    editor, md, _attach, _ = workspace
    md.load("abc [STRIKE]dead[/STRIKE] tail")
    editor.selectAll()
    editor.copy()
    mime = QApplication.clipboard().mimeData()
    assert mime.hasHtml()
    assert "<s" in mime.html() and "dead" in mime.html()
    assert mime.text() == "abc dead tail"  # markers stripped for plain
    # private marker format keeps in-board fidelity
    raw = bytes(mime.data(MARKER_MIME)).decode("utf-8")
    assert raw == "abc [STRIKE]dead[/STRIKE] tail"


def test_marker_mime_paste_roundtrips_strike(qtbot, workspace):
    editor, md, _attach, _ = workspace
    md.load("abc [STRIKE]dead[/STRIKE] tail")
    editor.selectAll()
    editor.copy()
    md.load("")
    editor.paste()
    assert md.serialize() == "abc [STRIKE]dead[/STRIKE] tail"


# ── INTERNAL link copy / paste ───────────────────────────────────────────

def test_object_copy_puts_internal_marker_and_file_url(qtbot, workspace):
    editor, md, attach, _ = workspace
    name = _paste_image(editor)
    pos = editor.document().toPlainText().index(OBJECT_CHAR)
    cursor = editor.textCursor()
    cursor.setPosition(pos)
    cursor.setPosition(pos + 1, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    editor.copy()
    mime = QApplication.clipboard().mimeData()
    assert mime.text() == f"[INTERNAL:image:{name}]"
    assert mime.hasUrls()
    assert mime.urls()[0].toLocalFile() == str(attach / name)


def test_internal_link_paste_reinserts_object(qtbot, workspace):
    editor, md, _attach, _ = workspace
    name = _paste_image(editor)
    # cursor to end, paste the marker text (as 复制链接 produces)
    platform_utils.copy_text(f"[INTERNAL:image:{name}]")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    editor.paste()
    assert md.serialize().count(f"[IMAGE:{name}]") == 2


def test_internal_file_link_paste_reinserts_chip(qtbot, workspace, tmp_path):
    editor, md, _attach, _ = workspace
    name = _paste_file(editor, tmp_path)
    platform_utils.copy_text(f"[INTERNAL:file:{name}]")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    editor.paste()
    assert md.serialize().count(f"[FILE:{name}]") == 2


def test_internal_link_missing_attachment_falls_through_to_text(
        qtbot, workspace):
    editor, md, _attach, _ = workspace
    marker = "[INTERNAL:image:ghost.png]"
    platform_utils.copy_text(marker)
    editor.paste()
    assert marker in md.serialize()  # literal text, no object
    assert OBJECT_CHAR not in editor.document().toPlainText()


# ── object context menus (v1 item sets) ──────────────────────────────────

def test_image_context_menu_matches_v1(qtbot, workspace):
    editor, md, _attach, _ = workspace
    tr = editor.translator.tr
    name = _paste_image(editor)  # pasted screenshot: no original path
    menu = editor.build_object_context_menu(_object_hit(editor, name, False))
    items = _menu_items(menu)
    assert [t for t, _e in items] == [
        tr("copy_link"), tr("copy_img_file"), tr("copy_file_path"),
        tr("show_in_finder"), tr("show_original"), tr("open_default"),
        tr("delete")]
    enabled = dict(items)
    assert enabled[tr("show_original")] is False  # original unknown
    for key in ("copy_link", "copy_img_file", "copy_file_path",
                "show_in_finder", "open_default", "delete"):
        assert enabled[tr(key)] is True

    # once the filename map records an original path, it lights up
    md.filename_map[name] = {"name": "shot.png", "path": "/tmp/shot.png"}
    menu = editor.build_object_context_menu(_object_hit(editor, name, False))
    assert dict(_menu_items(menu))[tr("show_original")] is True


def test_file_context_menu_matches_v1(qtbot, workspace, tmp_path):
    editor, md, attach, _ = workspace
    tr = editor.translator.tr
    name = _paste_file(editor, tmp_path)  # import records the original path
    menu = editor.build_object_context_menu(_object_hit(editor, name, True))
    items = _menu_items(menu)
    assert [t for t, _e in items] == [
        tr("copy_link"), tr("open_file"), tr("copy_file"),
        tr("copy_file_path"), tr("show_in_finder"), tr("show_original"),
        tr("delete")]
    assert all(e for _t, e in items)  # original recorded -> all enabled

    # missing attachment file: existence-dependent items gray out,
    # copy link / copy path / delete stay available (stable structure)
    (attach / name).unlink()
    menu = editor.build_object_context_menu(_object_hit(editor, name, True))
    enabled = dict(_menu_items(menu))
    for key in ("open_file", "copy_file", "show_in_finder"):
        assert enabled[tr(key)] is False
    for key in ("copy_link", "copy_file_path", "delete"):
        assert enabled[tr(key)] is True


def test_context_menu_copy_actions_write_clipboard(qtbot, workspace):
    editor, md, attach, _ = workspace
    tr = editor.translator.tr
    name = _paste_image(editor)
    menu = editor.build_object_context_menu(_object_hit(editor, name, False))
    actions = {a.text(): a for a in menu.actions() if not a.isSeparator()}
    actions[tr("copy_link")].trigger()
    assert QApplication.clipboard().text() == f"[INTERNAL:image:{name}]"
    actions[tr("copy_file_path")].trigger()
    assert QApplication.clipboard().text() == str(attach / name)
    actions[tr("copy_img_file")].trigger()  # staged temp copy w/ display name
    mime = QApplication.clipboard().mimeData()
    assert mime.hasUrls()
    assert os.path.basename(mime.urls()[0].toLocalFile()) == name  # no map


# ── update flow (monkeypatched, no network) ──────────────────────────────

@pytest.fixture
def window(qtbot, tmp_path):
    win = MainWindow(NoteStore(str(tmp_path)))
    qtbot.addWidget(win)
    return win


def _stubbed_flow(window, ask=True):
    flow = UpdateFlow(window, window.translator)
    log = {"asked": [], "alerts": [], "launched": [], "opened": []}
    flow._ask = lambda msg: (log["asked"].append(msg), ask)[1]
    flow._alert = lambda msg: log["alerts"].append(msg)
    flow.launch_installer = lambda p: log["launched"].append(p)
    flow.open_releases_page = lambda: log["opened"].append(True)
    return flow, log


def _release(tag, with_assets=True):
    assets = [("App.dmg", "http://x/App.dmg"),
              ("App.exe", "http://x/App.exe"),
              ("App.deb", "http://x/App.deb")] if with_assets else []
    return updater.ReleaseInfo(tag=tag, assets=assets)


def test_update_flow_newer_downloads_and_reaches_ready(
        qtbot, window, monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest",
                        lambda url, ua: _release("v99.0.0"))

    def fake_download(url, dest, ua, progress_cb=None):
        with open(dest, "wb") as f:
            f.write(b"installer-bytes")
        if progress_cb:
            progress_cb(50)
            progress_cb(100)

    monkeypatch.setattr(updater, "download", fake_download)
    flow, log = _stubbed_flow(window, ask=True)
    percents = []
    flow.download_progress.connect(percents.append)

    with qtbot.waitSignal(flow.finished, timeout=5000) as blocker:
        flow.check()
    assert blocker.args == ["ready"]
    assert len(log["launched"]) == 1
    assert os.path.exists(log["launched"][0])
    assert os.path.basename(log["launched"][0]).startswith("App.")
    assert percents == [50, 100]
    assert flow._progress_dlg is None  # progress dialog closed again
    tr = window.translator.tr
    assert log["asked"] == [tr("update_available").format("99.0.0", APP_VERSION)]
    assert log["alerts"] == [tr("update_ready_msg")]


def test_update_flow_up_to_date_alerts_update_none(
        qtbot, window, monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest",
                        lambda url, ua: _release("v1.0.0"))
    flow, log = _stubbed_flow(window)
    with qtbot.waitSignal(flow.finished, timeout=5000) as blocker:
        flow.check()
    assert blocker.args == ["none"]
    assert log["alerts"] == [window.translator.tr("update_none")
                             .format(APP_VERSION)]
    assert not log["launched"]


def test_update_flow_fetch_error_shows_failed_dialog(
        qtbot, window, monkeypatch):
    def boom(url, ua):
        raise OSError("no network")

    monkeypatch.setattr(updater, "fetch_latest", boom)
    flow, log = _stubbed_flow(window, ask=True)  # yes -> releases page
    with qtbot.waitSignal(flow.finished, timeout=5000) as blocker:
        flow.check()
    assert blocker.args == ["failed"]
    assert len(log["asked"]) == 1
    assert "no network" in log["asked"][0]
    assert log["opened"] == [True]
    assert not log["launched"]


def test_update_flow_silent_swallows_error_and_up_to_date(
        qtbot, window, monkeypatch):
    def boom(url, ua):
        raise OSError("offline")

    monkeypatch.setattr(updater, "fetch_latest", boom)
    flow, log = _stubbed_flow(window)
    with qtbot.waitSignal(flow.finished, timeout=5000) as blocker:
        flow.check(silent=True)
    assert blocker.args == ["silent-failed"]
    assert not log["asked"] and not log["alerts"]

    monkeypatch.setattr(updater, "fetch_latest",
                        lambda url, ua: _release("v2.0.0"))
    flow2, log2 = _stubbed_flow(window)
    with qtbot.waitSignal(flow2.finished, timeout=5000) as blocker:
        flow2.check(silent=True)
    assert blocker.args == ["none"]
    assert not log2["alerts"]


def test_update_flow_no_asset_offers_releases_page(
        qtbot, window, monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest",
                        lambda url, ua: _release("v99.0.0",
                                                 with_assets=False))
    flow, log = _stubbed_flow(window, ask=True)
    with qtbot.waitSignal(flow.finished, timeout=5000) as blocker:
        flow.check()
    assert blocker.args == ["no_asset"]
    assert log["asked"] == [window.translator.tr("update_no_asset")
                            .format("99.0.0")]
    assert log["opened"] == [True]


def test_update_flow_declined_stops(qtbot, window, monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest",
                        lambda url, ua: _release("v99.0.0"))
    flow, log = _stubbed_flow(window, ask=False)
    with qtbot.waitSignal(flow.finished, timeout=5000) as blocker:
        flow.check()
    assert blocker.args == ["declined"]
    assert not log["launched"]


def test_main_window_check_for_updates_wires_a_flow(
        qtbot, window, monkeypatch):
    """The 检查更新 menu item calls check_for_updates, which runs a real
    UpdateFlow kept alive on the window (silent + up-to-date: no UI)."""
    monkeypatch.setattr(updater, "fetch_latest",
                        lambda url, ua: _release("v1.0.0"))
    flow = window.check_for_updates(silent=True)
    assert window._update_flow is flow
    with qtbot.waitSignal(flow.finished, timeout=5000) as blocker:
        pass
    assert blocker.args == ["none"]
