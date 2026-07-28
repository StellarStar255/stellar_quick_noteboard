# Stellar Quick Noteboard

A lightweight, cross-platform desktop note-taking app built with Python and Qt (PySide6). Organize notes into notebooks, paste images directly from clipboard, pin the window on top, and switch between Chinese and English UI.

> v2.0 is a complete rewrite from Tkinter to Qt for a much faster editor
> (incremental per-line markdown rendering instead of full-document
> re-renders). The on-disk data format is unchanged — v1 and v2 open the
> same notebooks. The legacy Tk implementation is kept as
> `QuickNoteBoard.py`; the Qt app lives in `noteboard/` (`python -m noteboard`).

## Features

- Multiple notebooks with sidebar navigation
- Paste images from clipboard (requires Pillow)
- Outline / table of contents panel
- In-note find & replace (Cmd/Ctrl+F) and global search across all notebooks (Cmd/Ctrl+Shift+F)
- Markdown rendering with task-list checkboxes (`- [ ]` / `- [x]`, click to toggle) and code-block syntax highlighting
- Edit history and automatic backups, with in-app backup restore
- Export notebooks as ZIP, Markdown, or self-contained HTML
- Word / character count status bar
- Crash-safe atomic saves; backups and attachment cleanup run off the UI thread
- Pin-on-top window, adjustable UI font size and padding
- Light / dark themes
- Bilingual UI (中文 / English)

## Requirements

- Python 3.8+
- Tkinter (ships with most Python installs; on some Linux distros install `python3-tk`)
- [Pillow](https://pypi.org/project/Pillow/) — optional, needed for image paste

## Installation

### Download an installer (recommended)

Grab the latest installer from the [Releases page](https://github.com/StellarStar255/stellar_quick_noteboard/releases/latest):

| Platform | File |
| --- | --- |
| macOS (Apple Silicon) | `StellarQuickNoteboard-<version>-macOS.dmg` |
| Windows 10/11 (64-bit) | `StellarQuickNoteboard-<version>-Setup.exe` |
| Debian / Ubuntu | `stellar-quick-noteboard_<version>_amd64.deb` |

Installed builds store data in the per-user data directory (`~/Library/Application Support/StellarQuickNoteboard` on macOS, `%APPDATA%\StellarQuickNoteboard` on Windows, `~/.local/share/stellar-quick-noteboard` on Linux) and can self-update: Icon menu → "Check for Updates" downloads and launches the new installer.

### Run from source

```bash
git clone https://github.com/StellarStar255/stellar_quick_noteboard
cd stellar_quick_noteboard
pip install pyside6 Pillow
python -m noteboard          # Qt app (v2)
python QuickNoteBoard.py     # legacy Tk app (v1)
```

Platform notes:

- **macOS**: Python from [python.org](https://www.python.org/downloads/) or Homebrew (`brew install python-tk`) works out of the box.
- **Windows**: Tkinter is bundled with the official Python installer.
- **Linux**: install Tk and a CJK font if you need Chinese rendering, e.g.
  ```bash
  sudo apt install python3-tk fonts-noto-cjk
  ```

## Usage

Run the app from the project directory:

```bash
python QuickNoteBoard.py
```

On first launch a `notebooks/` folder is created with a default notebook. User preferences are stored in `config.json`, and periodic snapshots are written to `backups/`.

## Project layout

```
QuickNoteBoard.py   # main application
config.json         # user settings (auto-generated)
notebooks/          # your notebooks (auto-generated)
backups/            # automatic backups (auto-generated)
assets/             # bundled icons and resources
```

## License

Released under the [MIT License](LICENSE).
