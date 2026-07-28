"""One-click auto-update: macOS bundle swap + Windows silent install."""

import subprocess

import pytest

from noteboard.ui import platform_utils


def test_swap_script_contents():
    s = platform_utils.macos_swap_script(
        "/tmp/x.dmg", "/Applications/Stellar Quick Noteboard.app", 4242)
    assert 'kill -0 "4242"' in s
    assert '"/tmp/x.dmg"' in s
    assert '"/Applications/Stellar Quick Noteboard.app"' in s
    assert "hdiutil attach" in s and "hdiutil detach" in s
    assert "open -n" in s
    assert 'rm -f "$0"' in s  # helper cleans itself up


def test_bundle_path_none_when_not_frozen():
    # Test runs from a plain python interpreter — never inside a bundle.
    assert platform_utils.macos_bundle_path() is None


def test_launch_installer_darwin_bundled_spawns_helper(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(platform_utils.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform_utils, "macos_bundle_path",
                        lambda: str(tmp_path / "Fake.app"))
    monkeypatch.setattr(subprocess, "Popen",
                        lambda cmd, **kw: calls.append((cmd, kw)))
    platform_utils.launch_installer(str(tmp_path / "u.dmg"))
    (cmd, kw), = calls
    assert cmd[0] == "/bin/bash" and cmd[1].endswith(".sh")
    assert kw.get("start_new_session") is True


def test_launch_installer_darwin_source_falls_back_to_open(monkeypatch,
                                                           tmp_path):
    calls = []
    monkeypatch.setattr(platform_utils.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform_utils, "macos_bundle_path", lambda: None)
    monkeypatch.setattr(subprocess, "Popen",
                        lambda cmd, **kw: calls.append(cmd))
    platform_utils.launch_installer(str(tmp_path / "u.dmg"))
    assert calls == [["open", str(tmp_path / "u.dmg")]]


def test_launch_installer_windows_silent(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(platform_utils.platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "Popen",
                        lambda cmd, **kw: calls.append(cmd))
    platform_utils.launch_installer(str(tmp_path / "Setup.exe"))
    assert calls == [[str(tmp_path / "Setup.exe"), "/SILENT", "/NORESTART"]]
