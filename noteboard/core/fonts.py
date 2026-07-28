"""Platform font selection (no GUI imports).

Pure platform branches only — the v1 Tk-based Linux CJK rendering probe
(_validate_linux_cjk_font) belongs to the UI layer; here we only expose
the candidate list it walked.
"""

import platform

# Candidates: fontconfig names first (work when Tk has proper Xft),
# then X11 core font names (fallback for limited Tk setups).
LINUX_CJK_CANDIDATES = [
    "Noto Sans CJK SC", "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
    "Droid Sans Fallback", "Helvetica", "song ti", "gothic",
]


def system_font():
    """Get the best available system font for the current platform."""
    system = platform.system()
    if system == "Darwin":
        # Qt cannot resolve "SF Pro Text" by family name (Tk could); the
        # dot-name is how Qt addresses the San Francisco system font.
        return ".AppleSystemUIFont"
    elif system == "Windows":
        return "Segoe UI"
    # Linux: use Helvetica as initial default; the UI layer may refine it
    # against LINUX_CJK_CANDIDATES by testing actual rendering.
    return "Helvetica"


def mono_font():
    """Get the best available monospace font for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return "Menlo"
    elif system == "Windows":
        return "Consolas"
    return "DejaVu Sans Mono"
