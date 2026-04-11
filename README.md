# Stellar Quick Noteboard

A lightweight, cross-platform desktop note-taking app built with Python and Tkinter. Organize notes into notebooks, paste images directly from clipboard, pin the window on top, and switch between Chinese and English UI.

## Features

- Multiple notebooks with sidebar navigation
- Paste images from clipboard (requires Pillow)
- Outline / table of contents panel
- Full-text search across notes
- Edit history and automatic backups
- Pin-on-top window, adjustable UI font size and padding
- Light / dark themes
- Bilingual UI (中文 / English)

## Requirements

- Python 3.8+
- Tkinter (ships with most Python installs; on some Linux distros install `python3-tk`)
- [Pillow](https://pypi.org/project/Pillow/) — optional, needed for image paste

## Installation

```bash
git clone https://github.com/StellarStar255/stellar_quick_noteboard
cd stellar_quick_noteboard
pip install Pillow
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
