"""Attachment helpers for Quick Note Board (no Qt/Tk imports).

Ported from QuickNoteBoard.py (v1); marker formats and cleanup rules are
byte/semantics-compatible with v1:

- Note text references attachments with ``[IMAGE:filename]`` /
  ``[IMAGE:filename:width]`` and ``[FILE:filename]`` markers.
- Video thumbnails are cached in the attachments directory as
  ``_thumb_{filename}.png``; cleanup never deletes ``_thumb_*`` files
  directly, only the companion thumb of a deleted attachment.
- ``filename_map.json`` and dot-files are never touched by cleanup.

Note: v1's thumbnail generator uses macOS ``qlmanage`` (frame extraction)
and ``mdls`` (duration), not ffmpeg — ported verbatim.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Iterable

_IS_LINUX = platform.system() == "Linux"

# v1 NoteApp.VIDEO_EXTENSIONS
VIDEO_EXTS = {'.mp4', '.m4v', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm'}

# v1 marker regexes (cleanup_unused_attachments / load_content_with_images):
# [IMAGE:filename] or [IMAGE:filename:width], and [FILE:filename]
_IMAGE_RE = re.compile(r'\[IMAGE:([^:\]]+)(?::\d+)?\]')
_FILE_RE = re.compile(r'\[FILE:([^\]]+)\]')


def is_video_file(name: str) -> bool:
    """Check if *name* is a video file based on extension (v1 _is_video_file)."""
    ext = os.path.splitext(name)[1].lower()
    return ext in VIDEO_EXTS


def file_icon(display_name: str) -> str:
    """Emoji icon based on file extension (v1 get_file_icon, verbatim).

    On Linux, plain-text fallbacks are returned because X11 bitmap fonts
    cannot render emoji."""
    ext = os.path.splitext(display_name)[1].lower()

    if _IS_LINUX:
        # Plain-text icons for Linux (X11 bitmap fonts lack emoji)
        if ext in {'.mp4', '.m4v', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm'}:
            return '▶'
        elif ext in {'.mp3', '.wav', '.aac', '.flac', '.m4a', '.ogg', '.wma'}:
            return '♪'
        elif ext in {'.doc', '.docx', '.rtf', '.odt'}:
            return '¶'
        elif ext == '.pdf':
            return '¶'
        elif ext in {'.xls', '.xlsx', '.csv', '.ods'}:
            return '#'
        elif ext in {'.ppt', '.pptx', '.odp', '.key'}:
            return '▶'
        elif ext in {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}:
            return '■'
        elif ext in {'.py', '.js', '.html', '.css', '.java', '.c', '.cpp', '.h', '.swift', '.go', '.rs'}:
            return '<>'
        elif ext in {'.txt', '.md', '.json', '.xml', '.yaml', '.yml'}:
            return '='
        elif ext in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico'}:
            return '★'
        elif ext in {'.exe', '.app', '.dmg', '.pkg', '.deb', '.rpm'}:
            return '*'
        else:
            return '-'

    # Video files
    if ext in {'.mp4', '.m4v', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm'}:
        return '🎬'
    # Audio files
    elif ext in {'.mp3', '.wav', '.aac', '.flac', '.m4a', '.ogg', '.wma'}:
        return '🎵'
    # Document files
    elif ext in {'.doc', '.docx', '.rtf', '.odt'}:
        return '📝'
    # PDF
    elif ext == '.pdf':
        return '📕'
    # Spreadsheet
    elif ext in {'.xls', '.xlsx', '.csv', '.ods'}:
        return '📊'
    # Presentation
    elif ext in {'.ppt', '.pptx', '.odp', '.key'}:
        return '📽️'
    # Archive
    elif ext in {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}:
        return '📦'
    # Code
    elif ext in {'.py', '.js', '.html', '.css', '.java', '.c', '.cpp', '.h', '.swift', '.go', '.rs'}:
        return '💻'
    # Text
    elif ext in {'.txt', '.md', '.json', '.xml', '.yaml', '.yml'}:
        return '📄'
    # Image (non-embedded)
    elif ext in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico'}:
        return '🖼️'
    # Executable
    elif ext in {'.exe', '.app', '.dmg', '.pkg', '.deb', '.rpm'}:
        return '⚙️'
    # Default
    else:
        return '📎'


def referenced_attachments(content: str) -> set[str]:
    """Attachment filenames referenced in *content*, scanned with the exact
    v1 markers: [IMAGE:filename] / [IMAGE:filename:width] and [FILE:filename].

    Like v1, the scan is a plain regex over the whole text — markers are
    matched wherever they appear (v1 does not exclude code blocks etc.)."""
    image_refs = set(_IMAGE_RE.findall(content))
    file_refs = set(_FILE_RE.findall(content))
    return image_refs | file_refs


def cleanup_unused(attachments_dir: str, content: str,
                   keep_thumbs_for: Iterable[str] = (),
                   fresh_grace_seconds: float = 60.0) -> list[str]:
    """Remove attachments no longer referenced in *content*; return the
    deleted attachment names (thumb-cache companions are removed silently,
    exactly like v1 cleanup_unused_attachments).

    *keep_thumbs_for*: extra names to treat as referenced (v1 feeds the
    undo/redo stacks' references here) — their files and thumbnails are
    kept. Syncing filename_map.json is left to the caller (as in v1, where
    _finish_attachment_cleanup does it on the main thread).

    v1 rules, ported verbatim:
    - skip dot-files and ``filename_map.json``
    - skip ``_thumb_*`` thumbnail caches
    - skip referenced files
    - spare very fresh files (modified within *fresh_grace_seconds*): an
      attachment pasted while cleanup runs is not referenced yet
    - directories are removed with rmtree, files with remove
    - a deleted attachment's ``_thumb_{name}.png`` cache is also removed
    """
    referenced_files = referenced_attachments(content) | set(keep_thumbs_for)
    deleted: list[str] = []
    if not os.path.exists(attachments_dir):
        return deleted

    try:
        entries = os.listdir(attachments_dir)
    except OSError as e:
        print(f"Error cleaning up attachments: {e}")
        return deleted

    for filename in entries:
        # Skip special files and thumbnail caches
        if filename.startswith('.') or filename == 'filename_map.json':
            continue
        if filename.startswith('_thumb_'):
            continue
        if filename in referenced_files:
            continue
        filepath = os.path.join(attachments_dir, filename)
        try:
            # Spare very fresh files: an attachment pasted while cleanup
            # runs is not in referenced_files yet
            if time.time() - os.path.getmtime(filepath) < fresh_grace_seconds:
                continue
            if os.path.isdir(filepath):
                shutil.rmtree(filepath)
            else:
                os.remove(filepath)
            deleted.append(filename)

            # Remove associated video thumbnail cache
            thumb_cache = os.path.join(attachments_dir,
                                       f"_thumb_{filename}.png")
            if os.path.exists(thumb_cache):
                os.remove(thumb_cache)
        except OSError as e:
            print(f"Error removing {filename}: {e}")
    return deleted


def generate_video_thumbnail(video_path: str, thumb_path: str) -> bool:
    """Generate a video thumbnail (frame + play button + duration badge)
    and save it as PNG to *thumb_path*. Returns True on success.

    Port of v1 _generate_video_thumbnail: macOS-only — uses ``qlmanage``
    for frame extraction and ``mdls`` for duration, PIL for compositing.
    Returns False when PIL is unavailable, off macOS, or on any failure."""
    if platform.system() != "Darwin":
        return False  # macOS-only, as in v1
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False

    import tempfile
    tmp_dir = tempfile.mkdtemp()
    try:
        # Extract a frame using qlmanage
        result = subprocess.run(
            ["qlmanage", "-t", "-s", "600", "-o", tmp_dir, video_path],
            capture_output=True, timeout=5
        )
        if result.returncode != 0:
            return False

        # qlmanage outputs to tmp_dir/<filename>.png
        thumb_files = [f for f in os.listdir(tmp_dir) if f.endswith(".png")]
        if not thumb_files:
            return False

        frame = Image.open(os.path.join(tmp_dir, thumb_files[0])).convert("RGBA")

        # Get video duration using mdls
        duration_text = None
        try:
            result = subprocess.run(
                ["mdls", "-name", "kMDItemDurationSeconds", video_path],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                # Parse "kMDItemDurationSeconds = 123.456"
                for line in result.stdout.strip().split("\n"):
                    if "=" in line:
                        val = line.split("=")[1].strip()
                        if val != "(null)":
                            secs = int(float(val))
                            mins, secs = divmod(secs, 60)
                            hours, mins = divmod(mins, 60)
                            if hours > 0:
                                duration_text = f"{hours}:{mins:02d}:{secs:02d}"
                            else:
                                duration_text = f"{mins}:{secs:02d}"
        except Exception:
            pass  # Duration is optional

        # Draw play button overlay (center)
        overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        w, h = frame.size
        circle_r = min(w, h) // 8
        cx, cy = w // 2, h // 2

        # Semi-transparent dark circle
        draw.ellipse(
            [cx - circle_r, cy - circle_r, cx + circle_r, cy + circle_r],
            fill=(0, 0, 0, 160)
        )

        # White triangle (play icon) inside circle
        tri_size = circle_r * 0.6
        # Offset right slightly for visual centering of triangle
        tri_cx = cx + int(tri_size * 0.1)
        triangle = [
            (tri_cx - int(tri_size * 0.4), cy - int(tri_size * 0.6)),
            (tri_cx - int(tri_size * 0.4), cy + int(tri_size * 0.6)),
            (tri_cx + int(tri_size * 0.6), cy),
        ]
        draw.polygon(triangle, fill=(255, 255, 255, 230))

        # Duration badge (bottom-right)
        if duration_text:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/SFCompact.ttf", 18)
            except Exception:
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
                except Exception:
                    font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), duration_text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad_x, pad_y = 8, 4
            margin = 10
            rx = w - margin - tw - pad_x * 2
            ry = h - margin - th - pad_y * 2

            # Rounded rect background
            draw.rounded_rectangle(
                [rx, ry, rx + tw + pad_x * 2, ry + th + pad_y * 2],
                radius=6, fill=(0, 0, 0, 180)
            )
            draw.text((rx + pad_x, ry + pad_y), duration_text,
                      fill=(255, 255, 255, 240), font=font)

        # Composite overlay onto frame
        frame = Image.alpha_composite(frame, overlay)
        frame.convert("RGB").save(thumb_path, "PNG")
        return True

    except subprocess.TimeoutExpired:
        return False
    except Exception as e:
        print(f"Error generating video thumbnail: {e}")
        return False
    finally:
        # Clean up temp directory
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass
