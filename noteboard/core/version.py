"""App version and update-check constants (no GUI imports)."""

import re
import sys

APP_VERSION = "2.0.4"
GITHUB_REPO = "StellarStar255/stellar_quick_noteboard"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"

IS_FROZEN = getattr(sys, "frozen", False)


def parse_version(text):
    """'v1.2.3' / '1.2.3' -> (1, 2, 3); unparseable parts count as 0."""
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        m = re.match(r"\d+", chunk)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts or [0])
