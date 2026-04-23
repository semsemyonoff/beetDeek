"""Shared helpers and constants for beetDeek routes."""

import logging
import os
import re
import sqlite3
import sys
import threading

from flask import current_app

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("beetdeck")


class _BeetsLogAdapter(logging.LoggerAdapter):
    """Adapter that converts beets-style {} format strings to %s for stdlib."""

    def process(self, msg, kwargs):
        if "{}" in str(msg):
            msg = str(msg).replace("{}", "%s")
        return msg, kwargs


_beets_log = _BeetsLogAdapter(log, {})

# ---------------------------------------------------------------------------
# Cover art constants
# ---------------------------------------------------------------------------
COVER_NAMES = [
    "cover.jpg",
    "cover.png",
    "cover.jpeg",
    "folder.jpg",
    "folder.png",
    "folder.jpeg",
    "front.jpg",
    "front.png",
    "front.jpeg",
]

_COVER_STEMS = {"cover", "folder", "front"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

COVER_HIRES_MAX = 1200
COVER_EMBED_MAX = 500
COVER_EMBED_QUALITY = 70

# ---------------------------------------------------------------------------
# Beets initialization state
# ---------------------------------------------------------------------------
_beets_initialized = False
_beets_init_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _decode_path(val):
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return val or ""


def _resolve_path(path):
    """Decode path bytes and resolve relative paths against LIBRARY_ROOT.

    Beets 2.10.0 stores item/artpath values relative to the library root
    directory in the database. Absolute paths (pre-migration DBs) pass through
    unchanged for backward compatibility.
    """
    p = _decode_path(path)
    if not p or os.path.isabs(p):
        return p
    library_root = current_app.config.get("LIBRARY_ROOT", "")
    if library_root:
        return os.path.join(library_root, p)
    return p


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _get_ro_conn():
    library_db = current_app.config["LIBRARY_DB"]
    conn = sqlite3.connect(f"file:{library_db}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.create_function("ULOWER", 1, lambda s: s.lower() if s else s)
    return conn


# ---------------------------------------------------------------------------
# Cover helpers
# ---------------------------------------------------------------------------


def _find_lrc_file(item_path):
    """Find a .lrc file next to the audio file."""
    if not item_path:
        return None
    base = os.path.splitext(item_path)[0]
    lrc = base + ".lrc"
    if os.path.isfile(lrc):
        return lrc
    return None


def _read_lrc_file(lrc_path):
    """Read and return contents of a .lrc file."""
    try:
        with open(lrc_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _find_cover(album_dir):
    if not album_dir or not os.path.isdir(album_dir):
        return None
    for name in COVER_NAMES:
        p = os.path.join(album_dir, name)
        if os.path.isfile(p):
            return p
    return None


def _remove_cover_files(album_dir):
    """Remove all cover/folder/front image files from album directory."""
    if not album_dir or not os.path.isdir(album_dir):
        return
    for fname in os.listdir(album_dir):
        name_lower = fname.lower()
        stem, ext = os.path.splitext(name_lower)
        if ext not in _IMAGE_EXTS:
            continue
        base = stem.split(".")[0]
        if base in _COVER_STEMS:
            path = os.path.join(album_dir, fname)
            log.info("Removing old cover file: %s", path)
            os.remove(path)


def _resize_image(src_path, max_size, quality=95):
    """Resize image to fit max_size, return path to temp JPEG file."""
    import tempfile

    from PIL import Image

    img = Image.open(src_path)
    img.thumbnail((max_size, max_size), Image.LANCZOS)

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg", dir="/tmp")
    img.save(tmp, format="JPEG", quality=quality, optimize=True)
    tmp.close()
    return tmp.name


def _save_cover_to_album(album, src_path):
    """Save hi-res cover to album dir, embed smaller version into tracks.

    1. Resize source to 1200px max, best quality -> save to album dir
    2. Embed via beets with maxwidth=500, quality=70
    """
    from beets import art

    items = list(album.items())
    album_dir = os.path.dirname(_resolve_path(items[0].path)) if items else None
    _remove_cover_files(album_dir)

    hires_path = _resize_image(src_path, COVER_HIRES_MAX, quality=95)
    album.set_art(hires_path, False)
    album.store()
    if os.path.exists(hires_path):
        os.unlink(hires_path)

    art.embed_album(_beets_log, album, maxwidth=COVER_EMBED_MAX, quality=COVER_EMBED_QUALITY)


# ---------------------------------------------------------------------------
# Album directory helper
# ---------------------------------------------------------------------------


def _album_dir_from_items(conn, album_id):
    row = conn.execute("SELECT path FROM items WHERE album_id = ? LIMIT 1", (album_id,)).fetchone()
    if row:
        return os.path.dirname(_resolve_path(row["path"]))
    return None


# ---------------------------------------------------------------------------
# Genre formatting
# ---------------------------------------------------------------------------


def _format_genre(val):
    """Normalize a genre value (str with null-bytes or list) to a comma-separated string."""
    if isinstance(val, (list, tuple)):
        return ", ".join(str(v) for v in val)
    if isinstance(val, bytes):
        val = val.decode("utf-8", errors="replace")
    if not val:
        return ""
    val = str(val)
    parts = re.split(r"\\?\u2400|\x00", val)
    return ", ".join(p.strip() for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Beets initialization
# ---------------------------------------------------------------------------


def _init_beets(library_db):
    """Initialize beets config, load plugins, and return a Library instance.

    Accepts an explicit library_db path because this function may be called
    from background threads that have no Flask app context.
    """
    global _beets_initialized
    import beets
    import beets.library
    from beets import plugins

    beets.config.read(user=True, defaults=True)

    with _beets_init_lock:
        if not _beets_initialized:
            plugins.load_plugins()
            plugins.send("pluginload")
            _beets_initialized = True

            beets_log = logging.getLogger("beets")
            beets_log.setLevel(logging.DEBUG)

    return beets.library.Library(library_db)
