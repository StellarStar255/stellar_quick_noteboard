"""Pure update-check logic, ported from v1 check_for_updates worker,
_update_asset_suffix, _on_update_info and _download_and_run_update
(QuickNoteBoard.py ~L4369-4478). Threading/UI stays in the caller.

No Qt/Tk imports allowed in this module.
"""

import json
import re
import urllib.request
from dataclasses import dataclass, field

from noteboard.core import net


def parse_version(text):
    """'v1.2.3' / '1.2.3' -> (1, 2, 3); unparseable parts count as 0.
    (Local copy of v1 _parse_version, L63-69.)"""
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        m = re.match(r"\d+", chunk)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts or [0])


@dataclass
class ReleaseInfo:
    """Latest-release metadata from the GitHub Releases API."""
    tag: str
    assets: list = field(default_factory=list)  # list of (name, url) tuples


def fetch_latest(api_url, user_agent):
    """Query the GitHub Releases API for the latest release.

    Same request headers and timeout as the v1 worker (L4378-4390).
    Raises on network/JSON errors — the caller decides how to surface them.
    """
    req = urllib.request.Request(
        api_url,
        headers={"User-Agent": user_agent,
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10,
                                context=net.ssl_context()) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = data.get("tag_name") or ""
    assets = [(a.get("name") or "", a.get("browser_download_url") or "")
              for a in (data.get("assets") or [])]
    return ReleaseInfo(tag=tag, assets=assets)


def asset_suffix(system):
    """Installer suffix for a platform.system() value (v1 L4401-4403)."""
    return {"Darwin": ".dmg", "Windows": ".exe",
            "Linux": ".deb"}.get(system)


def pick_asset(assets, suffix):
    """Pick the first (name, url) asset matching *suffix* (v1 L4415-4416)."""
    return next(((n, u) for n, u in assets
                 if suffix and n.lower().endswith(suffix)), None)


def is_newer(tag, current_version):
    """True when *tag* is strictly newer than *current_version*
    (v1 tuple compare, L4407-4408)."""
    latest = parse_version(tag) if tag else (0,)
    return latest > parse_version(current_version)


def download(url, dest_path, user_agent, progress_cb=None):
    """Download *url* to *dest_path* in 64KB chunks (v1 worker, L4453-4468).

    progress_cb, when given, is called with an integer percentage (0-100)
    whenever the server provided a Content-Length.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=30,
                                context=net.ssl_context()) as resp, \
            open(dest_path, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and progress_cb is not None:
                progress_cb(done * 100 // total)
