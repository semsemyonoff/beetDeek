"""Genre routes blueprint."""
from flask import Blueprint, current_app, jsonify, request

from src.utils import _format_genre, _init_beets, log

bp = Blueprint("genres", __name__)


@bp.route("/api/album/<int:album_id>/genre", methods=["POST"])
def fetch_genre_preview(album_id):
    """Fetch genre from Last.fm without writing. Returns old and new values."""
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
                "old_genre": _format_genre(old_genre),
                "new_genre": _format_genre(new_genre),
            }
        )

    except Exception as e:
        log.exception("Genre preview failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500


@bp.route("/api/album/<int:album_id>/genre/confirm", methods=["POST"])
def confirm_genre(album_id):
    """Write the fetched genre to album and its tracks."""
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

        lib._close()
        return jsonify({"status": "ok", "genre": _format_genre(new_genre)})

    except Exception as e:
        log.exception("Genre confirm failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500


@bp.route("/api/album/<int:album_id>/genre/save", methods=["POST"])
def save_genre(album_id):
    """Manually set genre for album and its tracks."""
    try:
        genre = (request.json or {}).get("genre", "").strip()
        if not genre:
            return jsonify({"error": "Genre cannot be empty"}), 400

        library_db = current_app.config["LIBRARY_DB"]
        lib = _init_beets(library_db)
        album = lib.get_album(album_id)
        if not album:
            return jsonify({"error": "Album not found"}), 404

        genres_list = [g.strip() for g in genre.split(",") if g.strip()]
        album.genre = genres_list[0] if genres_list else genre
        if hasattr(album, "genres"):
            album.genres = genres_list
        album.store()
        for item in album.items():
            item.genre = genres_list[0] if genres_list else genre
            if hasattr(item, "genres"):
                item.genres = genres_list
            item.store()
            item.try_write()

        log.info("Genre manually set for album_id=%d: %s", album_id, genre)
        lib._close()
        return jsonify({"status": "ok", "genre": genre})

    except Exception as e:
        log.exception("Genre save failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500
