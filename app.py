import logging
import os
import sqlite3
import subprocess
import sys
import threading
import uuid

from flask import Flask, jsonify, render_template, send_file

app = Flask(__name__)

LIBRARY_DB = os.environ.get("BEETS_LIBRARY_DB", "/data/beets/library.db")
IMPORT_DIR = os.environ.get("BEETS_IMPORT_DIR", "/music")

# ---------------------------------------------------------------------------
# Logging — verbose beets output to container stdout
# ---------------------------------------------------------------------------
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("beetdeck")

_rescan_lock = threading.Lock()
_rescan_proc = None
_identify_tasks = {}
_identify_lock = threading.Lock()

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

# All possible cover file patterns (including numbered duplicates like cover.1.jpg)
_COVER_STEMS = {"cover", "folder", "front"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def _remove_cover_files(album_dir):
    """Remove all cover/folder/front image files from album directory."""
    if not album_dir or not os.path.isdir(album_dir):
        return
    for fname in os.listdir(album_dir):
        name_lower = fname.lower()
        stem, ext = os.path.splitext(name_lower)
        if ext not in _IMAGE_EXTS:
            continue
        # Match "cover", "cover.1", "folder", "front.2", etc.
        base = stem.split(".")[0]
        if base in _COVER_STEMS:
            path = os.path.join(album_dir, fname)
            log.info("Removing old cover file: %s", path)
            os.remove(path)


class _BeetsLogAdapter(logging.LoggerAdapter):
    """Adapter that converts beets-style {} format strings to %s for stdlib."""

    def process(self, msg, kwargs):
        if "{}" in str(msg):
            msg = str(msg).replace("{}", "%s")
        return msg, kwargs


_beets_log = _BeetsLogAdapter(log, {})


def _get_ro_conn():
    conn = sqlite3.connect(f"file:{LIBRARY_DB}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.create_function("ULOWER", 1, lambda s: s.lower() if s else s)
    return conn


def _decode_path(val):
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return val or ""


def _find_cover(album_dir):
    if not album_dir or not os.path.isdir(album_dir):
        return None
    for name in COVER_NAMES:
        p = os.path.join(album_dir, name)
        if os.path.isfile(p):
            return p
    return None


def _album_dir_from_items(conn, album_id):
    row = conn.execute(
        "SELECT path FROM items WHERE album_id = ? LIMIT 1", (album_id,)
    ).fetchone()
    if row:
        return os.path.dirname(_decode_path(row["path"]))
    return None


_beets_initialized = False


def _init_beets():
    """Initialize beets config, load plugins, and return a Library instance."""
    global _beets_initialized
    import beets
    import beets.library
    from beets import plugins

    beets.config.read(user=True, defaults=True)

    if not _beets_initialized:
        plugins.load_plugins()
        plugins.send("pluginload")
        _beets_initialized = True

        # Enable verbose logging for beets internals
        beets_log = logging.getLogger("beets")
        beets_log.setLevel(logging.DEBUG)

    return beets.library.Library(LIBRARY_DB)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/logo.svg")
def logo():
    return send_file("/app/logo.svg", mimetype="image/svg+xml")


# ---------------------------------------------------------------------------
# Library list
# ---------------------------------------------------------------------------


@app.route("/api/library")
def library():
    if not os.path.isfile(LIBRARY_DB):
        return jsonify({"error": "not_initialized"}), 503
    try:
        conn = _get_ro_conn()
        rows = conn.execute(
            """
            SELECT a.id, a.albumartist, a.album, a.original_year, a.year,
                   a.artpath,
                   (SELECT value FROM album_attributes
                    WHERE entity_id = a.id AND key = 'beetdeck_tagged') AS tagged
            FROM albums a
            ORDER BY a.albumartist COLLATE NOCASE, a.original_year, a.year, a.album
            """
        ).fetchall()
        conn.close()
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 500

    # Build a map of album_id -> directory from items table
    item_dirs = {}
    try:
        conn2 = _get_ro_conn()
        dir_rows = conn2.execute(
            "SELECT album_id, path FROM items GROUP BY album_id"
        ).fetchall()
        conn2.close()
        for dr in dir_rows:
            item_dirs[dr["album_id"]] = os.path.dirname(_decode_path(dr["path"]))
    except sqlite3.OperationalError:
        pass

    artists = {}
    for r in rows:
        artist = r["albumartist"] or "Unknown Artist"
        yr = r["original_year"] or r["year"] or None
        albums = artists.setdefault(artist, [])
        artpath = _decode_path(r["artpath"]) if r["artpath"] else None
        has_cover = bool(artpath and os.path.isfile(artpath))
        if not has_cover:
            has_cover = bool(_find_cover(item_dirs.get(r["id"])))
        albums.append(
            {
                "id": r["id"],
                "album": r["album"],
                "year": yr,
                "tagged": r["tagged"] == "1" if r["tagged"] else False,
                "has_cover": has_cover,
            }
        )

    result = [
        {"artist": name, "albums": albums}
        for name, albums in sorted(artists.items(), key=lambda x: x[0].lower())
    ]
    return jsonify(result)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@app.route("/api/search")
def search():
    from flask import request

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"artists": [], "albums": [], "tracks": []})

    like = f"%{q.lower()}%"
    try:
        conn = _get_ro_conn()

        # Artists (distinct albumartist names)
        artist_rows = conn.execute(
            """
            SELECT DISTINCT albumartist
            FROM albums
            WHERE ULOWER(albumartist) LIKE ?
            ORDER BY albumartist COLLATE NOCASE
            LIMIT 20
            """,
            (like,),
        ).fetchall()
        artists = [r["albumartist"] for r in artist_rows]

        # Albums
        album_rows = conn.execute(
            """
            SELECT a.id, a.album, a.albumartist, a.original_year, a.year, a.artpath
            FROM albums a
            WHERE ULOWER(a.album) LIKE ?
            ORDER BY a.albumartist COLLATE NOCASE, a.album COLLATE NOCASE
            LIMIT 30
            """,
            (like,),
        ).fetchall()
        # Build cover check map for found albums
        search_album_ids = [r["id"] for r in album_rows]
        search_item_dirs = {}
        if search_album_ids:
            ph = ",".join("?" * len(search_album_ids))
            sdir_rows = conn.execute(
                f"SELECT album_id, path FROM items WHERE album_id IN ({ph}) GROUP BY album_id",
                search_album_ids,
            ).fetchall()
            for dr in sdir_rows:
                search_item_dirs[dr["album_id"]] = os.path.dirname(
                    _decode_path(dr["path"])
                )

        albums = []
        for r in album_rows:
            artpath = _decode_path(r["artpath"]) if r["artpath"] else None
            has_cover = bool(artpath and os.path.isfile(artpath))
            if not has_cover:
                has_cover = bool(_find_cover(search_item_dirs.get(r["id"])))
            albums.append(
                {
                    "id": r["id"],
                    "album": r["album"],
                    "albumartist": r["albumartist"],
                    "year": r["original_year"] or r["year"] or None,
                    "has_cover": has_cover,
                }
            )

        # Tracks
        track_rows = conn.execute(
            """
            SELECT i.id, i.title, i.artist, i.album_id,
                   a.album, a.albumartist
            FROM items i
            JOIN albums a ON a.id = i.album_id
            WHERE ULOWER(i.title) LIKE ?
            ORDER BY i.title COLLATE NOCASE, i.artist COLLATE NOCASE
            LIMIT 30
            """,
            (like,),
        ).fetchall()
        tracks = [
            {
                "id": r["id"],
                "title": r["title"],
                "artist": r["artist"],
                "album_id": r["album_id"],
                "album": r["album"],
                "albumartist": r["albumartist"],
            }
            for r in track_rows
        ]

        conn.close()
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"artists": artists, "albums": albums, "tracks": tracks})


# ---------------------------------------------------------------------------
# Artist page
# ---------------------------------------------------------------------------


@app.route("/api/artist")
def artist_detail():
    from flask import request

    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Missing name"}), 400

    try:
        conn = _get_ro_conn()
        rows = conn.execute(
            """
            SELECT a.id, a.album, a.albumartist, a.original_year, a.year,
                   a.artpath,
                   (SELECT value FROM album_attributes
                    WHERE entity_id = a.id AND key = 'beetdeck_tagged') AS tagged
            FROM albums a
            WHERE a.albumartist = ?
            ORDER BY a.original_year, a.year, a.album
            """,
            (name,),
        ).fetchall()

        # Build cover check map
        item_dirs = {}
        if rows:
            album_ids = [r["id"] for r in rows]
            ph = ",".join("?" * len(album_ids))
            dir_rows = conn.execute(
                f"SELECT album_id, path FROM items WHERE album_id IN ({ph}) GROUP BY album_id",
                album_ids,
            ).fetchall()
            for dr in dir_rows:
                item_dirs[dr["album_id"]] = os.path.dirname(_decode_path(dr["path"]))

        conn.close()
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 500

    albums = []
    for r in rows:
        artpath = _decode_path(r["artpath"]) if r["artpath"] else None
        has_cover = bool(artpath and os.path.isfile(artpath))
        if not has_cover:
            has_cover = bool(_find_cover(item_dirs.get(r["id"])))
        albums.append(
            {
                "id": r["id"],
                "album": r["album"],
                "year": r["original_year"] or r["year"] or None,
                "tagged": r["tagged"] == "1" if r["tagged"] else False,
                "has_cover": has_cover,
            }
        )

    return jsonify({"artist": name, "albums": albums})


# ---------------------------------------------------------------------------
# Album detail
# ---------------------------------------------------------------------------


@app.route("/api/album/<int:album_id>")
def album_detail(album_id):
    try:
        conn = _get_ro_conn()
        a = conn.execute(
            """
            SELECT a.*,
                   (SELECT value FROM album_attributes
                    WHERE entity_id = a.id AND key = 'beetdeck_tagged') AS tagged
            FROM albums a WHERE a.id = ?
            """,
            (album_id,),
        ).fetchone()
        if not a:
            return jsonify({"error": "Album not found"}), 404

        items = conn.execute(
            """
            SELECT id, title, artist, track, disc, length, format, bitrate,
                   samplerate, path
            FROM items WHERE album_id = ? ORDER BY disc, track
            """,
            (album_id,),
        ).fetchall()

        album_dir = _album_dir_from_items(conn, album_id)
        artpath = _decode_path(a["artpath"]) if a["artpath"] else None
        has_cover = bool(artpath and os.path.isfile(artpath)) or bool(
            _find_cover(album_dir)
        )
        conn.close()
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 500

    def fmt_length(s):
        if not s:
            return ""
        m, sec = divmod(int(s), 60)
        return f"{m}:{sec:02d}"

    tracks = []
    for it in items:
        tracks.append(
            {
                "id": it["id"],
                "title": it["title"],
                "artist": it["artist"],
                "track": it["track"],
                "disc": it["disc"],
                "length": fmt_length(it["length"]),
                "format": it["format"],
                "bitrate": it["bitrate"],
                "samplerate": it["samplerate"],
            }
        )

    genre = ""
    if "genres" in a.keys():
        genre = a["genres"] or ""
    if not genre and "genre" in a.keys():
        genre = a["genre"] or ""

    return jsonify(
        {
            "id": a["id"],
            "album": a["album"],
            "albumartist": a["albumartist"],
            "year": a["original_year"] or a["year"] or None,
            "genre": genre,
            "label": a["label"] or "",
            "mb_albumid": a["mb_albumid"] or "",
            "path": album_dir or "",
            "has_cover": has_cover,
            "tagged": a["tagged"] == "1" if a["tagged"] else False,
            "tracks": tracks,
        }
    )


# ---------------------------------------------------------------------------
# Cover art
# ---------------------------------------------------------------------------


@app.route("/api/album/<int:album_id>/cover")
def album_cover(album_id):
    try:
        conn = _get_ro_conn()
        a = conn.execute(
            "SELECT artpath FROM albums WHERE id = ?", (album_id,)
        ).fetchone()
        album_dir = _album_dir_from_items(conn, album_id)
        conn.close()
    except sqlite3.OperationalError:
        return "", 404

    artpath = _decode_path(a["artpath"]) if a and a["artpath"] else None
    if artpath and os.path.isfile(artpath):
        return send_file(artpath)

    cover = _find_cover(album_dir)
    if cover:
        return send_file(cover)

    return "", 404


COVER_HIRES_MAX = 1200
COVER_EMBED_MAX = 500
COVER_EMBED_QUALITY = 70


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

    1. Resize source to 1200px max, best quality → save to album dir
    2. Embed via beets with maxwidth=500, quality=70
    """
    from beets import art

    album_dir = _decode_path(album.path) if album.path else None
    _remove_cover_files(album_dir)

    # 1. Hi-res for album directory
    hires_path = _resize_image(src_path, COVER_HIRES_MAX, quality=95)
    album.set_art(hires_path, False)
    album.store()
    if os.path.exists(hires_path):
        os.unlink(hires_path)

    # 2. Embed smaller version — beets resizes from artpath on the fly
    art.embed_album(
        _beets_log, album, maxwidth=COVER_EMBED_MAX, quality=COVER_EMBED_QUALITY
    )


# ---------------------------------------------------------------------------
# Cover art management
# ---------------------------------------------------------------------------


@app.route("/api/album/<int:album_id>/cover/fetch", methods=["POST"])
def fetch_cover(album_id):
    """Fetch cover art from online sources via fetchart plugin (preview)."""
    try:
        lib = _init_beets()
        album = lib.get_album(album_id)
        if not album:
            return jsonify({"error": "Album not found"}), 404

        from beets import plugins

        fetchart = None
        for p in plugins.find_plugins():
            if p.name == "fetchart":
                fetchart = p
                break
        if not fetchart:
            return jsonify({"error": "fetchart plugin not loaded"}), 500

        log.info(
            "Fetching cover art for album_id=%d: %s - %s",
            album_id,
            album.albumartist,
            album.album,
        )

        candidate = fetchart.art_for_album(album, paths=[], local_only=False)

        if not candidate or not candidate.path:
            log.info("No cover art found for album_id=%d", album_id)
            lib._close()
            return jsonify({"status": "ok", "found": False})

        # Store candidate path temporarily for confirm step
        _identify_tasks[f"cover_{album_id}"] = {
            "candidate_path": _decode_path(candidate.path),
            "source": getattr(candidate, "source_name", "unknown"),
        }

        log.info(
            "Cover art found for album_id=%d from %s: %s",
            album_id,
            getattr(candidate, "source_name", "?"),
            _decode_path(candidate.path),
        )

        lib._close()
        return jsonify(
            {
                "status": "ok",
                "found": True,
                "source": getattr(candidate, "source_name", "unknown"),
                "preview_url": f"/api/album/{album_id}/cover/preview",
            }
        )

    except Exception as e:
        log.exception("Cover fetch failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500


@app.route("/api/album/<int:album_id>/cover/preview")
def cover_preview(album_id):
    """Serve the fetched cover art candidate for preview."""
    task = _identify_tasks.get(f"cover_{album_id}")
    if not task or not task.get("candidate_path"):
        return "", 404
    path = task["candidate_path"]
    if os.path.isfile(path):
        return send_file(path)
    return "", 404


@app.route("/api/album/<int:album_id>/cover/confirm", methods=["POST"])
def confirm_cover(album_id):
    """Save fetched cover to album directory and embed into files."""
    task = _identify_tasks.pop(f"cover_{album_id}", None)
    if not task or not task.get("candidate_path"):
        return jsonify({"error": "No cover art to confirm"}), 400

    try:
        lib = _init_beets()
        album = lib.get_album(album_id)
        if not album:
            return jsonify({"error": "Album not found"}), 404

        candidate_path = task["candidate_path"]
        if not os.path.isfile(candidate_path):
            return jsonify({"error": "Cover art file not found"}), 404

        log.info("Saving cover art for album_id=%d from %s", album_id, candidate_path)

        _save_cover_to_album(album, candidate_path)

        log.info("Cover art saved and embedded for album_id=%d", album_id)
        lib._close()
        return jsonify({"status": "ok"})

    except Exception as e:
        log.exception("Cover confirm failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500


@app.route("/api/album/<int:album_id>/cover/upload", methods=["POST"])
def upload_cover(album_id):
    """Upload a cover art image, save to album dir and embed into files."""
    from flask import request

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    try:
        lib = _init_beets()
        album = lib.get_album(album_id)
        if not album:
            return jsonify({"error": "Album not found"}), 404

        # Save uploaded file to temp location
        import tempfile

        ext = os.path.splitext(f.filename)[1] or ".jpg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir="/tmp")
        f.save(tmp)
        tmp.close()

        log.info("Uploading cover art for album_id=%d: %s", album_id, f.filename)

        _save_cover_to_album(album, tmp.name)

        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

        log.info("Cover art uploaded and embedded for album_id=%d", album_id)
        lib._close()
        return jsonify({"status": "ok"})

    except Exception as e:
        log.exception("Cover upload failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Track tags
# ---------------------------------------------------------------------------


@app.route("/api/album/<int:album_id>/track/<int:item_id>/tags")
def track_tags(album_id, item_id):
    try:
        conn = _get_ro_conn()
        row = conn.execute(
            "SELECT * FROM items WHERE id = ? AND album_id = ?", (item_id, album_id)
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Track not found"}), 404

        attrs = conn.execute(
            "SELECT key, value FROM item_attributes WHERE entity_id = ?", (item_id,)
        ).fetchall()
        conn.close()
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 500

    skip = {"id", "album_id", "path"}
    tags = {}
    for key in row.keys():
        if key in skip:
            continue
        val = row[key]
        if isinstance(val, bytes):
            val = _decode_path(val)
        if val is not None and val != "" and val != 0 and val != 0.0:
            tags[key] = val

    for attr in attrs:
        val = attr["value"]
        if isinstance(val, bytes):
            val = val.decode("utf-8", errors="replace")
        tags[attr["key"]] = val

    return jsonify(tags)


# ---------------------------------------------------------------------------
# Rescan
# ---------------------------------------------------------------------------


@app.route("/api/rescan", methods=["POST"])
def rescan():
    from flask import request

    global _rescan_proc
    mode = request.args.get("mode", "quick")
    with _rescan_lock:
        if _rescan_proc and _rescan_proc.poll() is None:
            return jsonify({"status": "running"}), 409
        inc = "-i" if mode == "quick" else "-I"
        cmd = f"beet -v import -A -C {inc} {IMPORT_DIR} && beet -v update -M"
        log.info("Starting rescan (%s): %s", mode, cmd)
        _rescan_proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
    return jsonify({"status": "started", "mode": mode})


@app.route("/api/rescan/status")
def rescan_status():
    if _rescan_proc is None:
        return jsonify({"status": "idle"})
    if _rescan_proc.poll() is None:
        return jsonify({"status": "running"})
    return jsonify({"status": "done", "returncode": _rescan_proc.returncode})


# ---------------------------------------------------------------------------
# Genre (lastgenre)
# ---------------------------------------------------------------------------


@app.route("/api/album/<int:album_id>/genre", methods=["POST"])
def fetch_genre_preview(album_id):
    """Fetch genre from Last.fm without writing. Returns old and new values."""
    try:
        lib = _init_beets()
        album = lib.get_album(album_id)
        if not album:
            return jsonify({"error": "Album not found"}), 404

        from beets import plugins

        lastgenre = None
        for p in plugins.find_plugins():
            if p.name == "lastgenre":
                lastgenre = p
                break

        if not lastgenre:
            return jsonify({"error": "lastgenre plugin not loaded"}), 500

        old_genre = album.get("genres", "") or ""

        log.info(
            "Fetching genre preview for album_id=%d: %s - %s",
            album_id,
            album.albumartist,
            album.album,
        )

        # Fetch without writing (pretend mode)
        lastgenre.config["pretend"].set(True)
        try:
            lastgenre._process(album, write=False)
        finally:
            lastgenre.config["pretend"].set(False)

        new_genre = album.get("genres", "") or ""
        log.info(
            "Genre preview for album_id=%d: %r -> %r", album_id, old_genre, new_genre
        )

        # Restore old value (we only previewed)
        album.genres = old_genre
        album.store()

        lib._close()
        return jsonify(
            {
                "status": "ok",
                "old_genre": old_genre,
                "new_genre": new_genre,
            }
        )

    except Exception as e:
        log.exception("Genre preview failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500


@app.route("/api/album/<int:album_id>/genre/confirm", methods=["POST"])
def confirm_genre(album_id):
    """Write the fetched genre to album and its tracks."""
    try:
        lib = _init_beets()
        album = lib.get_album(album_id)
        if not album:
            return jsonify({"error": "Album not found"}), 404

        from beets import plugins

        lastgenre = None
        for p in plugins.find_plugins():
            if p.name == "lastgenre":
                lastgenre = p
                break

        if not lastgenre:
            return jsonify({"error": "lastgenre plugin not loaded"}), 500

        log.info(
            "Confirming genre for album_id=%d: %s - %s",
            album_id,
            album.albumartist,
            album.album,
        )

        lastgenre._process(album, write=True)

        new_genre = album.get("genres", "") or ""
        log.info("Genre written for album_id=%d: %s", album_id, new_genre)

        lib._close()
        return jsonify({"status": "ok", "genre": new_genre})

    except Exception as e:
        log.exception("Genre confirm failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Identification
# ---------------------------------------------------------------------------


def _serialize_candidate(idx, album_match):
    """Serialize an AlbumMatch to JSON-safe dict for the frontend."""
    info = album_match.info
    track_info = []
    for item, track in album_match.mapping.items():
        track_info.append(
            {
                "title": track.title,
                "track": track.index,
                "artist": track.artist or info.artist,
                "length": f"{int(track.length) // 60}:{int(track.length) % 60:02d}"
                if track.length
                else "",
                "current_title": item.title,
            }
        )

    return {
        "index": idx,
        "artist": info.artist,
        "album": info.album,
        "year": info.year,
        "media": getattr(info, "media", "") or "",
        "data_source": info.data_source,
        "mb_albumid": info.album_id or "",
        "distance": round(float(album_match.distance), 4),
        "track_count": len(info.tracks),
        "tracks": sorted(track_info, key=lambda t: t.get("track", 0)),
    }


def _run_identify(task_id, album_id, search_artist, search_album, search_id):
    """Background thread: run beets autotag and store candidates."""
    task = _identify_tasks[task_id]
    try:
        from beets import autotag

        log.info(
            "Identify album_id=%d artist=%r album=%r id=%r",
            album_id,
            search_artist,
            search_album,
            search_id,
        )

        lib = _init_beets()
        album = lib.get_album(album_id)
        if not album:
            task["status"] = "error"
            task["error"] = "Album not found"
            return

        items = list(album.items())
        if not items:
            task["status"] = "error"
            task["error"] = "No tracks in album"
            return

        task["current_artist"] = album.albumartist
        task["current_album"] = album.album

        search_ids = [search_id] if search_id else []

        log.info(
            "Running tag_album for %r - %r (%d items)",
            album.albumartist,
            album.album,
            len(items),
        )

        try:
            artist, album_name, proposal = autotag.tag_album(
                items,
                search_artist=search_artist or None,
                search_name=search_album or None,
                search_ids=search_ids or [],
            )
        except Exception as e:
            log.exception("Autotag failed for album_id=%d", album_id)
            task["status"] = "error"
            task["error"] = f"Autotag failed: {e}"
            return

        # Store raw AlbumMatch objects for apply/confirm, and lib for later use
        matches = list(proposal.candidates[:5])
        matches.sort(key=lambda m: float(m.distance))

        task["_matches"] = matches
        task["_lib"] = lib

        candidates = [_serialize_candidate(i, m) for i, m in enumerate(matches)]

        for c in candidates:
            log.info(
                "Candidate: %r - %r (dist=%.4f, source=%s)",
                c["artist"],
                c["album"],
                c["distance"],
                c["data_source"],
            )

        log.info(
            "Identify done for album_id=%d: %d candidates", album_id, len(candidates)
        )
        task["candidates"] = candidates
        task["status"] = "done"

    except Exception as e:
        log.exception("Identify error for album_id=%d", album_id)
        task["status"] = "error"
        task["error"] = str(e)


def _get_task_json(task):
    """Return JSON-serializable copy of task (without internal objects)."""
    return {k: v for k, v in task.items() if not k.startswith("_")}


@app.route("/api/album/<int:album_id>/identify", methods=["POST"])
def identify(album_id):
    from flask import request

    data = request.get_json(silent=True) or {}

    with _identify_lock:
        existing = _identify_tasks.get(f"album_{album_id}")
        if existing and existing.get("status") == "running":
            return jsonify({"status": "running", "task_id": existing["task_id"]}), 409

        task_id = str(uuid.uuid4())[:8]
        task = {
            "task_id": task_id,
            "album_id": album_id,
            "status": "running",
            "candidates": [],
            "current_artist": "",
            "current_album": "",
            "error": None,
        }
        _identify_tasks[f"album_{album_id}"] = task

    t = threading.Thread(
        target=_run_identify,
        args=(
            f"album_{album_id}",
            album_id,
            data.get("artist", ""),
            data.get("album", ""),
            data.get("search_id", ""),
        ),
        daemon=True,
    )
    t.start()

    return jsonify({"status": "started", "task_id": task_id})


@app.route("/api/album/<int:album_id>/identify/status")
def identify_status(album_id):
    task = _identify_tasks.get(f"album_{album_id}")
    if not task:
        return jsonify({"status": "idle"})
    return jsonify(_get_task_json(task))


# ---------------------------------------------------------------------------
# Apply match (preview diff)
# ---------------------------------------------------------------------------


@app.route("/api/album/<int:album_id>/apply", methods=["POST"])
def apply_match(album_id):
    """Preview what would change if this candidate is applied."""
    from flask import request

    data = request.get_json(silent=True) or {}
    candidate_index = data.get("candidate_index", 0)

    task = _identify_tasks.get(f"album_{album_id}")
    if not task or task["status"] != "done":
        return jsonify({"error": "No identification results"}), 400

    matches = task.get("_matches", [])
    if candidate_index < 0 or candidate_index >= len(matches):
        return jsonify({"error": "Invalid candidate index"}), 400

    album_match = matches[candidate_index]
    info = album_match.info

    # Build diff from merged_pairs (what beets would actually write)
    track_diffs = []
    for item, new_data in album_match.merged_pairs:
        diff_entry = {"track": item.track}
        for field in ["title", "artist"]:
            old_val = getattr(item, field, "") or ""
            new_val = new_data.get(field, old_val) or ""
            diff_entry[field] = {"old": str(old_val), "new": str(new_val)}
        track_diffs.append(diff_entry)
    track_diffs.sort(key=lambda t: t["track"])

    # Album-level diff
    try:
        conn = _get_ro_conn()
        a = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
        conn.close()
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 500

    album_data = info.item_data if hasattr(info, "item_data") else {}
    album_diff = {}
    for field in ["album", "albumartist", "year", "label", "mb_albumid"]:
        old_val = a[field] if a[field] is not None else ""
        if field == "mb_albumid":
            new_val = info.album_id or ""
        elif field == "albumartist":
            new_val = album_data.get("albumartist", info.artist) or ""
        elif field == "album":
            new_val = album_data.get("album", info.album) or ""
        elif field == "year":
            new_val = album_data.get("year", info.year) or ""
        else:
            new_val = album_data.get(field, "") or ""
        album_diff[field] = {"old": str(old_val), "new": str(new_val)}

    return jsonify(
        {
            "candidate_index": candidate_index,
            "album": album_diff,
            "tracks": track_diffs,
        }
    )


# ---------------------------------------------------------------------------
# Confirm (write tags)
# ---------------------------------------------------------------------------


@app.route("/api/album/<int:album_id>/confirm", methods=["POST"])
def confirm_match(album_id):
    """Apply the selected match using beets API and write tags to files."""
    from flask import request

    data = request.get_json(silent=True) or {}
    candidate_index = data.get("candidate_index", 0)

    task = _identify_tasks.get(f"album_{album_id}")
    if not task or task["status"] != "done":
        return jsonify({"error": "No identification results"}), 400

    matches = task.get("_matches", [])
    if candidate_index < 0 or candidate_index >= len(matches):
        return jsonify({"error": "Invalid candidate index"}), 400

    album_match = matches[candidate_index]

    try:
        lib = task.get("_lib") or _init_beets()
        album = lib.get_album(album_id)
        if not album:
            return jsonify({"error": "Album not found"}), 404

        log.info(
            "Confirming match for album_id=%d: %r - %r (source=%s, dist=%.4f)",
            album_id,
            album_match.info.artist,
            album_match.info.album,
            album_match.info.data_source,
            float(album_match.distance),
        )

        # Apply track-level metadata via beets API
        album_match.apply_metadata()
        for item in album_match.mapping.keys():
            item.store()
            item.write()
            log.info("Wrote tags for track %d: %s", item.track, item.title)

        # Apply album-level metadata via beets API
        album_match.apply_album_metadata(album)
        album.store()

        # Mark as tagged
        album.beetdeck_tagged = "1"
        album.store()

        log.info("Album %d tagged successfully", album_id)

        # Clean up task
        task.pop("_matches", None)
        task.pop("_lib", None)

    except Exception as e:
        log.exception("Confirm failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Lyrics
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


@app.route("/api/album/<int:album_id>/track/<int:item_id>/lyrics")
def track_lyrics(album_id, item_id):
    """Get current lyrics for a track (from DB/tags or external .lrc file)."""
    try:
        conn = _get_ro_conn()
        row = conn.execute(
            "SELECT lyrics, path FROM items WHERE id = ? AND album_id = ?",
            (item_id, album_id),
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Track not found"}), 404
        conn.close()
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 500

    lyrics_text = row["lyrics"] or ""
    item_path = _decode_path(row["path"])

    # Check for external .lrc file
    lrc_path = _find_lrc_file(item_path)
    lrc_text = _read_lrc_file(lrc_path) if lrc_path else None

    if lyrics_text:
        return jsonify(
            {
                "has_lyrics": True,
                "lyrics": lyrics_text,
                "source": "embedded",
            }
        )
    elif lrc_text:
        return jsonify(
            {
                "has_lyrics": True,
                "lyrics": lrc_text,
                "source": "lrc_file",
                "lrc_path": lrc_path,
            }
        )
    else:
        return jsonify({"has_lyrics": False, "lyrics": "", "source": None})


@app.route(
    "/api/album/<int:album_id>/track/<int:item_id>/lyrics/fetch", methods=["POST"]
)
def fetch_track_lyrics(album_id, item_id):
    """Fetch lyrics for a single track from online sources (preview)."""
    try:
        lib = _init_beets()
        item = lib.get_item(item_id)
        if not item or item.album_id != album_id:
            return jsonify({"error": "Track not found"}), 404

        from beets import plugins

        lyrics_plugin = None
        for p in plugins.find_plugins():
            if p.name == "lyrics":
                lyrics_plugin = p
                break
        if not lyrics_plugin:
            return jsonify({"error": "lyrics plugin not loaded"}), 500

        log.info(
            "Fetching lyrics for item_id=%d: %s - %s", item_id, item.artist, item.title
        )

        result = lyrics_plugin.find_lyrics(item)

        if not result or not result.text:
            log.info("No lyrics found for item_id=%d", item_id)
            lib._close()
            return jsonify({"status": "ok", "found": False})

        # Store for confirm step
        _identify_tasks[f"lyrics_{item_id}"] = {
            "_lyrics_obj": result,
        }

        old_lyrics = item.lyrics or ""
        item_path = _decode_path(item.path) if item.path else None
        lrc_path = _find_lrc_file(item_path)
        lrc_text = _read_lrc_file(lrc_path) if lrc_path else None
        current_lyrics = old_lyrics or lrc_text or ""
        current_source = (
            "embedded" if old_lyrics else ("lrc_file" if lrc_text else None)
        )

        log.info(
            "Lyrics found for item_id=%d from %s", item_id, result.backend or "unknown"
        )

        lib._close()
        return jsonify(
            {
                "status": "ok",
                "found": True,
                "new_lyrics": result.full_text,
                "new_synced": result.synced,
                "new_backend": result.backend or "unknown",
                "current_lyrics": current_lyrics,
                "current_source": current_source,
            }
        )

    except Exception as e:
        log.exception("Lyrics fetch failed for item_id=%d", item_id)
        return jsonify({"error": str(e)}), 500


@app.route(
    "/api/album/<int:album_id>/track/<int:item_id>/lyrics/confirm", methods=["POST"]
)
def confirm_track_lyrics(album_id, item_id):
    """Write fetched lyrics to a single track."""
    task = _identify_tasks.pop(f"lyrics_{item_id}", None)
    if not task or not task.get("_lyrics_obj"):
        return jsonify({"error": "No lyrics to confirm"}), 400

    try:
        lib = _init_beets()
        item = lib.get_item(item_id)
        if not item or item.album_id != album_id:
            return jsonify({"error": "Track not found"}), 404

        new_lyrics = task["_lyrics_obj"]

        for key in ("backend", "url", "language", "translation_language"):
            item_key = f"lyrics_{key}"
            value = getattr(new_lyrics, key, None)
            if value:
                item[item_key] = value

        item.lyrics = new_lyrics.full_text
        item.store()
        item.try_write()

        log.info("Lyrics written for item_id=%d", item_id)

        item_path = _decode_path(item.path) if item.path else None
        lrc_path = _find_lrc_file(item_path)
        if lrc_path:
            os.remove(lrc_path)
            log.info("Removed .lrc file: %s", lrc_path)

        lib._close()
        return jsonify({"status": "ok"})

    except Exception as e:
        log.exception("Lyrics confirm failed for item_id=%d", item_id)
        return jsonify({"error": str(e)}), 500


@app.route(
    "/api/album/<int:album_id>/track/<int:item_id>/lyrics/embed", methods=["POST"]
)
def embed_lrc_lyrics(album_id, item_id):
    """Embed lyrics from external .lrc file into track and delete the .lrc."""
    try:
        lib = _init_beets()
        item = lib.get_item(item_id)
        if not item or item.album_id != album_id:
            return jsonify({"error": "Track not found"}), 404

        item_path = _decode_path(item.path) if item.path else None
        lrc_path = _find_lrc_file(item_path)
        if not lrc_path:
            return jsonify({"error": "No .lrc file found"}), 404

        lrc_text = _read_lrc_file(lrc_path)
        if not lrc_text:
            return jsonify({"error": "Could not read .lrc file"}), 500

        item.lyrics = lrc_text
        item.store()
        item.try_write()

        os.remove(lrc_path)
        log.info("Embedded .lrc and removed file for item_id=%d: %s", item_id, lrc_path)

        lib._close()
        return jsonify({"status": "ok"})

    except Exception as e:
        log.exception("Embed .lrc failed for item_id=%d", item_id)
        return jsonify({"error": str(e)}), 500


@app.route(
    "/api/album/<int:album_id>/track/<int:item_id>/lyrics/save", methods=["POST"]
)
def save_track_lyrics(album_id, item_id):
    """Manually save edited lyrics to a track."""
    from flask import request

    data = request.get_json(silent=True) or {}
    lyrics_text = data.get("lyrics", "")

    try:
        lib = _init_beets()
        item = lib.get_item(item_id)
        if not item or item.album_id != album_id:
            return jsonify({"error": "Track not found"}), 404

        item.lyrics = lyrics_text
        item.store()
        item.try_write()

        # Remove .lrc file if exists (we now have embedded lyrics)
        item_path = _decode_path(item.path) if item.path else None
        lrc_path = _find_lrc_file(item_path)
        if lrc_path and lyrics_text:
            os.remove(lrc_path)
            log.info("Removed .lrc file after manual edit: %s", lrc_path)

        log.info("Lyrics manually saved for item_id=%d", item_id)
        lib._close()
        return jsonify({"status": "ok"})

    except Exception as e:
        log.exception("Lyrics save failed for item_id=%d", item_id)
        return jsonify({"error": str(e)}), 500


@app.route("/api/album/<int:album_id>/lyrics/fetch", methods=["POST"])
def fetch_album_lyrics(album_id):
    """Fetch lyrics for all tracks in an album (preview)."""
    try:
        lib = _init_beets()
        album = lib.get_album(album_id)
        if not album:
            return jsonify({"error": "Album not found"}), 404

        from beets import plugins

        lyrics_plugin = None
        for p in plugins.find_plugins():
            if p.name == "lyrics":
                lyrics_plugin = p
                break
        if not lyrics_plugin:
            return jsonify({"error": "lyrics plugin not loaded"}), 500

        items = list(album.items())
        items.sort(key=lambda it: (it.disc, it.track))

        log.info(
            "Fetching lyrics for album_id=%d: %s - %s (%d tracks)",
            album_id,
            album.albumartist,
            album.album,
            len(items),
        )

        results = []
        for item in items:
            item_path = _decode_path(item.path) if item.path else None
            lrc_path = _find_lrc_file(item_path)
            lrc_text = _read_lrc_file(lrc_path) if lrc_path else None
            current_lyrics = item.lyrics or lrc_text or ""
            current_source = (
                "embedded" if item.lyrics else ("lrc_file" if lrc_text else None)
            )

            found_lyrics = lyrics_plugin.find_lyrics(item)

            entry = {
                "item_id": item.id,
                "track": item.track,
                "disc": item.disc,
                "title": item.title,
                "artist": item.artist,
                "current_lyrics": current_lyrics,
                "current_source": current_source,
                "found": False,
                "new_lyrics": "",
                "new_synced": False,
                "new_backend": "",
            }

            if found_lyrics and found_lyrics.text:
                entry["found"] = True
                entry["new_lyrics"] = found_lyrics.full_text
                entry["new_synced"] = found_lyrics.synced
                entry["new_backend"] = found_lyrics.backend or "unknown"

                _identify_tasks[f"lyrics_{item.id}"] = {
                    "_lyrics_obj": found_lyrics,
                }

                log.info(
                    "Lyrics found for %s - %s from %s",
                    item.artist,
                    item.title,
                    found_lyrics.backend or "unknown",
                )
            else:
                log.info("No lyrics found for %s - %s", item.artist, item.title)

            results.append(entry)

        lib._close()
        return jsonify({"status": "ok", "tracks": results})

    except Exception as e:
        log.exception("Album lyrics fetch failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500


@app.route("/api/album/<int:album_id>/lyrics/confirm", methods=["POST"])
def confirm_album_lyrics(album_id):
    """Write fetched lyrics for selected tracks in album."""
    from flask import request

    data = request.get_json(silent=True) or {}
    item_ids = data.get("item_ids", [])

    if not item_ids:
        return jsonify({"error": "No tracks selected"}), 400

    try:
        lib = _init_beets()
        written = 0

        for item_id in item_ids:
            task = _identify_tasks.pop(f"lyrics_{item_id}", None)
            if not task or not task.get("_lyrics_obj"):
                continue

            item = lib.get_item(item_id)
            if not item or item.album_id != album_id:
                continue

            new_lyrics = task["_lyrics_obj"]

            for key in ("backend", "url", "language", "translation_language"):
                item_key = f"lyrics_{key}"
                value = getattr(new_lyrics, key, None)
                if value:
                    item[item_key] = value

            item.lyrics = new_lyrics.full_text
            item.store()
            item.try_write()

            item_path = _decode_path(item.path) if item.path else None
            lrc_path = _find_lrc_file(item_path)
            if lrc_path:
                os.remove(lrc_path)
                log.info("Removed .lrc file: %s", lrc_path)

            written += 1
            log.info("Lyrics written for item_id=%d", item_id)

        lib._close()
        return jsonify({"status": "ok", "written": written})

    except Exception as e:
        log.exception("Album lyrics confirm failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500
