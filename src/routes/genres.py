"""Genre routes blueprint."""

import threading

from flask import Blueprint, current_app, jsonify, request

from src.utils import _format_genre, _init_beets, log

bp = Blueprint("genres", __name__)

# Serialize concurrent lastgenre preview calls: the beets lastgenre plugin
# stores pretend state as a singleton config key, so concurrent requests would
# corrupt each other's pretend flag without mutual exclusion.
_genre_plugin_lock = threading.Lock()


@bp.route("/api/album/<int:album_id>/genre", methods=["POST"])
def fetch_genre_preview(album_id):
    """Fetch genre from Last.fm without writing. Returns old and new values."""
    lib = None
    try:
        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
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

        # Fetch without writing (pretend mode); restore old value unconditionally.
        # Hold _genre_plugin_lock for the entire sequence: lastgenre.config is a
        # singleton, and concurrent preview requests would otherwise race on the
        # pretend flag (thread A sets True, thread B sets False, thread A runs
        # _process with pretend=False and actually writes the genre).
        with _genre_plugin_lock:
            lastgenre.config["pretend"].set(True)
            try:
                lastgenre._process(album, write=False)
                new_genre = album.get("genres", "") or ""
            finally:
                lastgenre.config["pretend"].set(False)
                album.genres = old_genre
                album.store()

        log.info("Genre preview for album_id=%d: %r -> %r", album_id, old_genre, new_genre)

        return jsonify(
            {
                "status": "ok",
                "old_genre": _format_genre(old_genre),
                "new_genre": _format_genre(new_genre),
            }
        )

    except Exception as e:
        log.exception("Genre preview failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500
    finally:
        if lib:
            lib._close()


@bp.route("/api/album/<int:album_id>/genre/confirm", methods=["POST"])
def confirm_genre(album_id):
    """Write the fetched genre to album and its tracks."""
    lib = None
    try:
        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
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

        return jsonify({"status": "ok", "genre": _format_genre(new_genre)})

    except Exception as e:
        log.exception("Genre confirm failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500
    finally:
        if lib:
            lib._close()


@bp.route("/api/album/<int:album_id>/genre/save", methods=["POST"])
def save_genre(album_id):
    """Manually set genre for album and its tracks."""
    genre = (request.json or {}).get("genre", "").strip()
    if not genre:
        return jsonify({"error": "Genre cannot be empty"}), 400

    lib = None
    try:
        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
        album = lib.get_album(album_id)
        if not album:
            return jsonify({"error": "Album not found"}), 404

        genres_list = [g.strip() for g in genre.split(",") if g.strip()]
        # beets 2.10.0: genres is the native list field; genre (singular) is
        # deprecated and removed in 3.0. Write only to genres.
        album.genres = genres_list
        album.store()
        for item in album.items():
            item.genres = genres_list
            item.store()
            item.try_write()

        log.info("Genre manually set for album_id=%d: %s", album_id, genre)
        return jsonify({"status": "ok", "genre": genre})

    except Exception as e:
        log.exception("Genre save failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500
    finally:
        if lib:
            lib._close()
