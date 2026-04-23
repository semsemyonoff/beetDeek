"""Library routes: SPA index, album list, search, and artist detail."""

import os
import sqlite3

from flask import Blueprint, jsonify, render_template, request

from src.utils import _decode_path, _find_cover, _get_ro_conn

bp = Blueprint("library", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/api/library")
def library():
    from flask import current_app

    if not os.path.isfile(current_app.config["LIBRARY_DB"]):
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

    item_dirs = {}
    try:
        conn2 = _get_ro_conn()
        dir_rows = conn2.execute("SELECT album_id, path FROM items GROUP BY album_id").fetchall()
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


@bp.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"artists": [], "albums": [], "tracks": []})

    like = f"%{q.lower()}%"
    try:
        conn = _get_ro_conn()

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

        search_album_ids = [r["id"] for r in album_rows]
        search_item_dirs = {}
        if search_album_ids:
            ph = ",".join("?" * len(search_album_ids))
            sdir_rows = conn.execute(
                f"SELECT album_id, path FROM items WHERE album_id IN ({ph}) GROUP BY album_id",
                search_album_ids,
            ).fetchall()
            for dr in sdir_rows:
                search_item_dirs[dr["album_id"]] = os.path.dirname(_decode_path(dr["path"]))

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


@bp.route("/api/artist")
def artist_detail():
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
