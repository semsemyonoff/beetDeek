"""Identification routes for beetDeek.

Endpoints:
    POST   /api/album/<id>/identify         — start background autotag
    GET    /api/album/<id>/identify/status  — poll task status
    POST   /api/album/<id>/apply            — preview diff for a candidate
    POST   /api/album/<id>/confirm          — write chosen candidate to files/DB
"""

import sqlite3
import threading
import uuid

from flask import Blueprint, current_app, jsonify, request

from src import state
from src.utils import _get_ro_conn, _init_beets, log

bp = Blueprint("identify", __name__)


# ---------------------------------------------------------------------------
# Private helpers (identify-specific)
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
        "label": getattr(info, "label", "") or "",
        "media": getattr(info, "media", "") or "",
        "data_source": info.data_source,
        "mb_albumid": info.album_id or "",
        "distance": round(float(album_match.distance), 4),
        "track_count": len(info.tracks),
        "tracks": sorted(track_info, key=lambda t: t.get("track", 0)),
    }


def _get_task_json(task):
    """Return JSON-serializable copy of task (without internal objects)."""
    return {k: v for k, v in task.items() if not k.startswith("_")}


def _run_identify(task_id, album_id, search_artist, search_album, search_id, library_db):
    """Background thread: run beets autotag and store candidates.

    Receives library_db as an explicit argument because background threads
    have no Flask app context (current_app would raise RuntimeError).
    """
    task = state.identify_tasks[task_id]
    lib = None
    try:
        from beets import autotag

        log.info(
            "Identify album_id=%d artist=%r album=%r id=%r",
            album_id,
            search_artist,
            search_album,
            search_id,
        )

        lib = _init_beets(library_db)
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

        matches = list(proposal.candidates[:5])
        matches.sort(key=lambda m: float(m.distance))

        candidates = [_serialize_candidate(i, m) for i, m in enumerate(matches)]

        for c in candidates:
            log.info(
                "Candidate: %r - %r (dist=%.4f, source=%s)",
                c["artist"],
                c["album"],
                c["distance"],
                c["data_source"],
            )

        log.info("Identify done for album_id=%d: %d candidates", album_id, len(candidates))

        # Transfer ownership of lib to task so confirm_match can reuse it.
        # Set lib=None to prevent the finally block from closing it.
        task["_matches"] = matches
        task["_lib"] = lib
        lib = None
        task["candidates"] = candidates
        task["status"] = "done"

    except Exception as e:
        log.exception("Identify error for album_id=%d", album_id)
        task["status"] = "error"
        task["error"] = str(e)
    finally:
        if lib is not None:
            lib._close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@bp.route("/api/album/<int:album_id>/identify", methods=["POST"])
def identify(album_id):
    data = request.get_json(silent=True) or {}

    library_db = current_app.config["LIBRARY_DB"]

    with state.identify_lock:
        existing = state.identify_tasks.get(f"album_{album_id}")
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
        state.identify_tasks[f"album_{album_id}"] = task

    t = threading.Thread(
        target=_run_identify,
        args=(
            f"album_{album_id}",
            album_id,
            data.get("artist", ""),
            data.get("album", ""),
            data.get("search_id", ""),
            library_db,
        ),
        daemon=True,
    )
    t.start()

    return jsonify({"status": "started", "task_id": task_id})


@bp.route("/api/album/<int:album_id>/identify/status")
def identify_status(album_id):
    task = state.identify_tasks.get(f"album_{album_id}")
    if not task:
        return jsonify({"status": "idle"})
    return jsonify(_get_task_json(task))


@bp.route("/api/album/<int:album_id>/apply", methods=["POST"])
def apply_match(album_id):
    """Preview what would change if this candidate is applied."""
    data = request.get_json(silent=True) or {}
    candidate_index = data.get("candidate_index", 0)

    task = state.identify_tasks.get(f"album_{album_id}")
    if not task or task["status"] != "done":
        return jsonify({"error": "No identification results"}), 400

    matches = task.get("_matches", [])
    if candidate_index < 0 or candidate_index >= len(matches):
        return jsonify({"error": "Invalid candidate index"}), 400

    album_match = matches[candidate_index]
    info = album_match.info

    track_diffs = []
    for item, new_data in album_match.merged_pairs:
        diff_entry = {"track": item.track}
        for field in ["title", "artist"]:
            old_val = getattr(item, field, "") or ""
            new_val = new_data.get(field, old_val) or ""
            diff_entry[field] = {"old": str(old_val), "new": str(new_val)}
        track_diffs.append(diff_entry)
    track_diffs.sort(key=lambda t: t["track"])

    try:
        conn = _get_ro_conn()
        try:
            a = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
        finally:
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


@bp.route("/api/album/<int:album_id>/confirm", methods=["POST"])
def confirm_match(album_id):
    """Apply the selected match using beets API and write tags to files."""
    data = request.get_json(silent=True) or {}
    candidate_index = data.get("candidate_index", 0)

    task = state.identify_tasks.get(f"album_{album_id}")
    if not task or task["status"] != "done":
        return jsonify({"error": "No identification results"}), 400

    matches = task.get("_matches", [])
    if candidate_index < 0 or candidate_index >= len(matches):
        return jsonify({"error": "Invalid candidate index"}), 400

    album_match = matches[candidate_index]

    lib = task.get("_lib") or _init_beets(current_app.config["LIBRARY_DB"])
    task.pop("_lib", None)
    try:
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

        album_match.apply_metadata()
        for item in album_match.mapping.keys():
            item.store()
            item.try_write()
            log.info("Wrote tags for track %d: %s", item.track, item.title)

        album_match.apply_album_metadata(album)
        album.store()

        album.beetdeck_tagged = "1"
        album.store()

        log.info("Album %d tagged successfully", album_id)

        task.pop("_matches", None)
        return jsonify({"status": "ok"})

    except Exception as e:
        log.exception("Confirm failed for album_id=%d", album_id)
        return jsonify({"error": str(e)}), 500
    finally:
        lib._close()
