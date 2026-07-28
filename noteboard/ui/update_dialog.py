"""In-app update flow (M7).

Port of the v1 UX (QuickNoteBoard.py check_for_updates L4369-4499) on top
of the pure logic in core.updater:

- network fetch on the global thread pool; all UI back on the GUI thread
  via queued signals;
- fetch error       -> yes/no dialog (update_failed) -> releases page;
- up to date        -> update_none alert (suppressed when silent);
- no platform asset -> yes/no dialog (update_no_asset) -> releases page;
- newer             -> confirm (update_available) -> download to a
  tempfile.mkdtemp dir with a themed progress dialog (percent label) ->
  launch the installer (platform_utils.launch_installer) ->
  update_ready_msg alert -> window.close() (the normal close path, so
  everything saves).

The dialog helpers (_ask/_alert) and launch_installer are plain
attributes so tests can stub them; ``finished`` reports the terminal
state ("failed" / "none" / "no_asset" / "declined" / "ready" /
"silent-failed").
"""

import os
import platform
import tempfile

from PySide6.QtCore import QObject, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel

from noteboard.core import updater
from noteboard.core.version import (APP_VERSION, RELEASES_API_URL,
                                    RELEASES_PAGE_URL)
from noteboard.ui import dialogs, platform_utils
from noteboard.ui.dialogs import StyledDialog

USER_AGENT = f"StellarQuickNoteboard/{APP_VERSION}"


class DownloadProgressDialog(StyledDialog):
    """v1 _download_and_run_update's progress Toplevel: a themed label
    counting '正在下载更新... NN%'."""

    def __init__(self, parent, tr):
        super().__init__(parent, tr("update_title"))
        self._base = tr("update_downloading")
        self._label = QLabel(self._base, self._card)
        self.body.addSpacing(12)
        self.body.addWidget(self._label)
        self.setMinimumWidth(320)

    def set_percent(self, percent):
        self._label.setText(f"{self._base} {percent}%")


class UpdateFlow(QObject):
    """One update check + optional download/install, v1-shaped."""

    #: (ReleaseInfo | None, Exception | None) from the fetch worker
    fetch_finished = Signal(object, object)
    #: (dest path, Exception | None) from the download worker
    download_finished = Signal(str, object)
    #: integer percent from core.updater.download
    download_progress = Signal(int)
    #: terminal state, mainly for tests
    finished = Signal(str)

    def __init__(self, window, translator):
        super().__init__(window)
        self._window = window
        self._tr = translator.tr
        self._silent = False
        self._progress_dlg = None
        self.launch_installer = platform_utils.launch_installer  # stubbable
        self.fetch_finished.connect(self._on_fetch_done)
        self.download_finished.connect(self._on_download_done)
        self.download_progress.connect(self._on_progress)

    # dialog seams (stubbable in tests) ---------------------------------

    def _ask(self, message):
        return dialogs.ask_confirm(self._window, self._tr,
                                   self._tr("update_title"), message)

    def _alert(self, message):
        dialogs.show_alert(self._window, self._tr,
                           self._tr("update_title"), message)

    def open_releases_page(self):
        QDesktopServices.openUrl(QUrl(RELEASES_PAGE_URL))

    # flow ---------------------------------------------------------------

    def check(self, silent=False):
        """v1 check_for_updates: fetch on a worker, decide on the GUI
        thread. silent=True (startup) swallows errors and 'up to date'."""
        self._silent = silent

        def worker():
            try:
                info = updater.fetch_latest(RELEASES_API_URL, USER_AGENT)
            except Exception as e:
                self.fetch_finished.emit(None, e)
                return
            self.fetch_finished.emit(info, None)

        QThreadPool.globalInstance().start(worker)

    def _show_error(self, error):
        """v1 _show_update_error: askyesno -> open the releases page."""
        if self._ask(self._tr("update_failed").format(error)):
            self.open_releases_page()

    def _on_fetch_done(self, info, error):
        tr = self._tr
        if error is not None:
            if self._silent:
                self.finished.emit("silent-failed")
                return
            self._show_error(error)
            self.finished.emit("failed")
            return
        if not updater.is_newer(info.tag, APP_VERSION):
            if not self._silent:
                self._alert(tr("update_none").format(APP_VERSION))
            self.finished.emit("none")
            return
        new_ver = info.tag.lstrip("vV")
        suffix = updater.asset_suffix(platform.system())
        asset = updater.pick_asset(info.assets, suffix)
        if asset is None:
            # v1 shows this even on the silent startup check
            if self._ask(tr("update_no_asset").format(new_ver)):
                self.open_releases_page()
            self.finished.emit("no_asset")
            return
        if not self._ask(tr("update_available").format(new_ver,
                                                       APP_VERSION)):
            self.finished.emit("declined")
            return
        self._start_download(asset[0], asset[1])

    def _start_download(self, filename, url):
        self._progress_dlg = DownloadProgressDialog(self._window, self._tr)
        self._progress_dlg.show()

        def worker():
            try:
                dest = os.path.join(tempfile.mkdtemp(prefix="sqn_update_"),
                                    filename)
                updater.download(url, dest, USER_AGENT,
                                 progress_cb=self.download_progress.emit)
            except Exception as e:
                self.download_finished.emit("", e)
                return
            self.download_finished.emit(dest, None)

        QThreadPool.globalInstance().start(worker)

    def _on_progress(self, percent):
        if self._progress_dlg is not None:
            self._progress_dlg.set_percent(percent)

    def _on_download_done(self, dest, error):
        if self._progress_dlg is not None:
            self._progress_dlg.close()
            self._progress_dlg = None
        if error is not None:
            self._show_error(error)
            self.finished.emit("failed")
            return
        # v1 _launch_update: start the installer, tell the user, then go
        # through the app's normal close path so everything saves.
        try:
            self.launch_installer(dest)
        except Exception as e:
            self._show_error(e)
            self.finished.emit("failed")
            return
        # mac (bundle swap) and Windows (silent Inno) auto-install and
        # relaunch; Linux hands the .deb to the system installer manually.
        auto = platform.system() in ("Darwin", "Windows")
        if auto and platform.system() == "Darwin":
            auto = platform_utils.macos_bundle_path() is not None
        self._alert(self._tr("update_auto_msg" if auto
                             else "update_ready_msg"))
        self.finished.emit("ready")
        # Really quit — with the tray active, close() would only hide the
        # window and the installer would wait on the process forever.
        quit_fn = getattr(self._window, "quit_app", self._window.close)
        quit_fn()
