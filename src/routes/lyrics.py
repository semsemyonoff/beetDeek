"""Lyrics routes blueprint."""
import os

from flask import Blueprint, current_app, jsonify, request

from src import state
from src.utils import _decode_path, _get_ro_conn, _init_beets, log

bp = Blueprint("lyrics", __name__)


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


@bp.route("/api/album/<int:album_id>/track/<int:item_id>/lyrics")
def track_lyrics(album_id, item_id):
    """Get current lyrics for a track (from DB/tags or external .lrc file)."""
    import sqlite3

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


@bp.route(
    "/api/album/<int:album_id>/track/<int:item_id>/lyrics/fetch", methods=["POST"]
)
def fetch_track_lyrics(album_id, item_id):
    """Fetch lyrics for a single track from online sources (preview)."""
    try:
        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
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

        with state.identify_lock:
            state.identify_tasks[f"lyrics_{item_id}"] = {
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


@bp.route(
    "/api/album/<int:album_id>/track/<int:item_id>/lyrics/confirm", methods=["POST"]
)
def confirm_track_lyrics(album_id, item_id):
    """Write fetched lyrics to a single track."""
    with state.identify_lock:
        task = state.identify_tasks.pop(f"lyrics_{item_id}", None)
    if not task or not task.get("_lyrics_obj"):
        return jsonify({"error": "No lyrics to confirm"}), 400

    try:
        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
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


@bp.route(
    "/api/album/<int:album_id>/track/<int:item_id>/lyrics/embed", methods=["POST"]
)
def embed_lrc_lyrics(album_id, item_id):
    """Embed lyrics from external .lrc file into track and delete the .lrc."""
    try:
        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
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


@bp.route("/api/album/<int:album_id>/lyrics/embed", methods=["POST"])
def embed_all_lrc(album_id):
    """Embed all external .lrc files for an album into tracks."""
    try:
        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
        album = lib.get_album(album_id)
        if not album:
            return jsonify({"error": "Album not found"}), 404

        embedded = []
        for item in album.items():
            item_path = _decode_path(item.path) if item.path else None
            lrc_path = _find_lrc_file(item_path)
            if not lrc_path:
                continue
            lrc_text = _read_lrc_file(lrc_path)
            if not lrc_text:
                continue
            item.lyrics = lrc_text
            item.store()
            item.try_write()
            os.remove(lrc_path)
            embedded.append({"id": item.id, "title": item.title})
            log.info("Embedded .lrc for item_id=%d: %s", item.id, lrc_path)

        lib._close()
        return jsonify({"status": "ok", "embedded": embedded})

    except Exception as e:
        log.exception("Embed all .lrc failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500


@bp.route(
    "/api/album/<int:album_id>/track/<int:item_id>/lyrics/save", methods=["POST"]
)
def save_track_lyrics(album_id, item_id):
    """Manually save edited lyrics to a track."""
    data = request.get_json(silent=True) or {}
    lyrics_text = data.get("lyrics", "")

    try:
        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
        item = lib.get_item(item_id)
        if not item or item.album_id != album_id:
            return jsonify({"error": "Track not found"}), 404

        item.lyrics = lyrics_text
        item.store()
        item.try_write()

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


@bp.route("/api/album/<int:album_id>/lyrics/fetch", methods=["POST"])
def fetch_album_lyrics(album_id):
    """Fetch lyrics for all tracks in an album (preview)."""
    try:
        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
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

                with state.identify_lock:
                    state.identify_tasks[f"lyrics_{item.id}"] = {
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


@bp.route("/api/album/<int:album_id>/lyrics/confirm", methods=["POST"])
def confirm_album_lyrics(album_id):
    """Write fetched lyrics for selected tracks in album."""
    data = request.get_json(silent=True) or {}
    item_ids = data.get("item_ids", [])

    if not item_ids:
        return jsonify({"error": "No tracks selected"}), 400

    try:
        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
        written = 0

        for item_id in item_ids:
            with state.identify_lock:
                task = state.identify_tasks.pop(f"lyrics_{item_id}", None)
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
