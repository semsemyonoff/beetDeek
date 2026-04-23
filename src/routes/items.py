"""Items routes for beetDeek — management of untagged/loose items.

Design decisions:
- Album creation from loose items: lib.add_album(items) creates a new album
  record and updates each item's album_id in the DB. This is NOT atomic with
  file tag writes. Strategy: (1) create album + apply DB metadata first,
  (2) then write tags to files. On DB failure: rollback via album.remove()
  and restore original album_id on each item. On partial file-write failure:
  DB state is committed; already-written files retain new tags (best-effort).
  Warnings are returned in the response — the caller can re-run or fix manually.
- Item reassignment: items may already belong to another album (e.g. a
  catch-all "Unknown" album). After confirm, the old album may become empty;
  we do NOT auto-delete it — that is the user's responsibility.
- Autotag input: autotag.tag_album() receives Item objects loaded via
  lib.get_item(id). The resulting AlbumMatch.mapping keys are those same items.
  No temporary album is created for the autotag step; it operates on items
  directly.

Endpoints:
    GET    /api/items/untagged                          — list items with NULL/empty albumartist
    POST   /api/items/<item_id>/metadata                — update artist/album on single item
    POST   /api/items/identify                          — start background identification
    GET    /api/items/identify/<task_id>/status         — poll identification status
    POST   /api/items/identify/<task_id>/apply          — preview diff for a candidate
    POST   /api/items/identify/<task_id>/confirm        — create album and write tags
"""

import threading

from flask import Blueprint, current_app, jsonify, request

from src import state
from src.utils import _get_ro_conn, _init_beets, _resolve_path, log

bp = Blueprint("items", __name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _serialize_candidate(idx, album_match):
    """Serialize an AlbumMatch to a JSON-safe dict."""
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
    return {k: v for k, v in task.items() if not k.startswith("_")}


def _run_items_identify(task_key, item_ids, search_artist, search_album, library_db):
    """Background thread: run beets autotag on a list of item IDs."""
    task = state.identify_tasks[task_key]
    lib = None
    try:
        from beets import autotag

        log.info(
            "Items identify task=%s item_ids=%r artist=%r album=%r",
            task_key,
            item_ids,
            search_artist,
            search_album,
        )

        lib = _init_beets(library_db)

        items = []
        for item_id in item_ids:
            item = lib.get_item(item_id)
            if item is None:
                task["status"] = "error"
                task["error"] = f"Item {item_id} not found"
                return
            items.append(item)

        if not items:
            task["status"] = "error"
            task["error"] = "No items to identify"
            return

        try:
            _artist, _album_name, proposal = autotag.tag_album(
                items,
                search_artist=search_artist or None,
                search_name=search_album or None,
                search_ids=[],
            )
        except Exception as e:
            log.exception("Autotag failed for items task %s", task_key)
            task["status"] = "error"
            task["error"] = f"Autotag failed: {e}"
            return

        matches = list(proposal.candidates[:5])
        matches.sort(key=lambda m: float(m.distance))
        candidates = [_serialize_candidate(i, m) for i, m in enumerate(matches)]

        log.info("Items identify done task=%s: %d candidates", task_key, len(candidates))

        task["_matches"] = matches
        task["_lib"] = lib
        lib = None
        task["candidates"] = candidates
        task["status"] = "done"

    except Exception as e:
        log.exception("Items identify error task=%s", task_key)
        task["status"] = "error"
        task["error"] = str(e)
    finally:
        if lib is not None:
            lib._close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@bp.route("/api/items/untagged")
def untagged_items():
    """Return items belonging to albums with NULL or empty albumartist."""
    try:
        conn = _get_ro_conn()
        try:
            rows = conn.execute(
                """
                SELECT i.id, i.title, i.artist, i.album, i.path, i.track,
                       i.album_id, a.albumartist
                FROM items i
                JOIN albums a ON a.id = i.album_id
                WHERE (a.albumartist IS NULL OR a.albumartist = '')
                ORDER BY i.album, i.track, i.title
                """
            ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    result = []
    for r in rows:
        path = r["path"]
        if isinstance(path, bytes):
            path = path.decode("utf-8", errors="replace")
        result.append(
            {
                "id": r["id"],
                "title": r["title"] or "",
                "artist": r["artist"] or "",
                "album": r["album"] or "",
                "path": path,
                "track": r["track"] or 0,
                "album_id": r["album_id"],
            }
        )
    return jsonify(result)


@bp.route("/api/items/<int:item_id>/metadata", methods=["POST"])
def update_metadata(item_id):
    """Update artist and album fields on a single item via beets Library."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    artist = (data.get("artist") or "").strip()
    album = (data.get("album") or "").strip()

    if not title and not artist and not album:
        return jsonify({"error": "At least one of title, artist, or album must be provided"}), 400

    library_db = current_app.config["LIBRARY_DB"]
    lib = None
    try:
        lib = _init_beets(library_db)
        item = lib.get_item(item_id)
        if item is None:
            return jsonify({"error": "Item not found"}), 404

        if title:
            item.title = title
        if artist:
            item.artist = artist
        if album:
            item.album = album
        item.store()

        if not item.try_write():
            log.warning("Failed to write tags for item %d after metadata update", item_id)
            return jsonify({"status": "ok", "item_id": item_id, "warnings": ["file tag write failed"]}), 200

        return jsonify({"status": "ok", "item_id": item_id})
    except Exception as e:
        log.exception("Failed to update metadata for item %d", item_id)
        return jsonify({"error": str(e)}), 500
    finally:
        if lib is not None:
            lib._close()


@bp.route("/api/items/identify", methods=["POST"])
def items_identify():
    """Start background identification for a list of item IDs."""
    data = request.get_json(silent=True) or {}
    item_ids = data.get("item_ids", [])
    search_artist = data.get("search_artist", "")
    search_album = data.get("search_album", "")

    if not item_ids:
        return jsonify({"error": "item_ids must be a non-empty list"}), 400

    if not isinstance(item_ids, list) or not all(isinstance(i, int) for i in item_ids):
        return jsonify({"error": "item_ids must be a list of integers"}), 400

    import uuid

    library_db = current_app.config["LIBRARY_DB"]

    task_id = str(uuid.uuid4())[:8]
    task_key = f"items_{task_id}"

    task = {
        "task_id": task_id,
        "item_ids": item_ids,
        "status": "running",
        "candidates": [],
        "error": None,
    }
    with state.identify_lock:
        # Close _lib for any previously completed items tasks that were never confirmed.
        # Items tasks are UUID-keyed so old done tasks accumulate; clean them up here
        # to avoid leaking open SQLite connections.
        stale_keys = [
            k
            for k, v in state.identify_tasks.items()
            if k.startswith("items_") and v.get("status") in ("done", "error") and v.get("_lib") is not None
        ]
        for k in stale_keys:
            old_lib = state.identify_tasks[k].pop("_lib", None)
            if old_lib is not None:
                try:
                    old_lib._close()
                except Exception:
                    pass
        state.identify_tasks[task_key] = task

    t = threading.Thread(
        target=_run_items_identify,
        args=(task_key, item_ids, search_artist, search_album, library_db),
        daemon=True,
    )
    t.start()

    return jsonify({"status": "started", "task_id": task_id})


@bp.route("/api/items/identify/<task_id>/status")
def items_identify_status(task_id):
    task_key = f"items_{task_id}"
    with state.identify_lock:
        task = state.identify_tasks.get(task_key)
        task_json = _get_task_json(task) if task else None
    if task_json is None:
        return jsonify({"status": "idle"})
    return jsonify(task_json)


@bp.route("/api/items/identify/<task_id>/apply", methods=["POST"])
def items_apply(task_id):
    """Preview what would change if the selected candidate is applied."""
    data = request.get_json(silent=True) or {}
    candidate_index = data.get("candidate_index", 0)

    task_key = f"items_{task_id}"
    with state.identify_lock:
        task = state.identify_tasks.get(task_key)
        if not task or task.get("status") != "done":
            return jsonify({"error": "No identification results"}), 400
        matches = task.get("_matches", [])

    if candidate_index < 0 or candidate_index >= len(matches):
        return jsonify({"error": "Invalid candidate index"}), 400

    album_match = matches[candidate_index]
    info = album_match.info

    track_diffs = []
    for item, track_info in album_match.mapping.items():
        diff_entry = {"track": item.track}
        for field in ["title", "artist"]:
            old_val = getattr(item, field, "") or ""
            new_val = getattr(track_info, field, old_val) or ""
            diff_entry[field] = {"old": str(old_val), "new": str(new_val)}
        track_diffs.append(diff_entry)
    track_diffs.sort(key=lambda t: t["track"])

    # Album-level diff: items are loose (no existing album), old values are empty
    album_data = info.item_data if hasattr(info, "item_data") else {}
    album_diff = {}
    for field in ["album", "albumartist", "year", "label", "mb_albumid"]:
        old_val = ""
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


@bp.route("/api/items/identify/<task_id>/confirm", methods=["POST"])
def items_confirm(task_id):
    """Create a new album from items and write matched tags to files."""
    data = request.get_json(silent=True) or {}
    candidate_index = data.get("candidate_index", 0)

    task_key = f"items_{task_id}"
    lib = None
    with state.identify_lock:
        task = state.identify_tasks.get(task_key)
        if not task or task.get("status") != "done":
            return jsonify({"error": "No identification results"}), 400
        matches = task.get("_matches", [])
        if candidate_index < 0 or candidate_index >= len(matches):
            return jsonify({"error": "Invalid candidate index"}), 400
        task["status"] = "confirming"
        lib = task.pop("_lib", None)

    album_match = matches[candidate_index]
    item_ids = task.get("item_ids", [])

    if lib is None:
        lib = _init_beets(current_app.config["LIBRARY_DB"])

    try:
        # Load item objects and record original album_ids for rollback
        items = []
        original_album_ids = {}
        for item_id in item_ids:
            item = lib.get_item(item_id)
            if item is None:
                task["status"] = "done"
                return jsonify({"error": f"Item {item_id} not found"}), 404
            items.append(item)
            original_album_ids[item_id] = item.album_id

        log.info(
            "Confirming items identify task=%s candidate=%d: %r - %r",
            task_id,
            candidate_index,
            album_match.info.artist,
            album_match.info.album,
        )

        # Create new album record first; on failure nothing has been modified yet
        album = None
        try:
            album = lib.add_album(items)
        except Exception as e:
            log.exception("Failed to create album for items task %s", task_id)
            for item in items:
                item.album_id = original_album_ids.get(item.id, item.album_id)
                item.store()
            task["status"] = "done"
            return jsonify({"error": f"Failed to create album: {e}"}), 500

        # Sync the new album_id onto mapping items (they are different Python objects
        # from the fresh items passed to add_album, which already had album_id set).
        for item in album_match.mapping.keys():
            item.album_id = album.id

        # Apply track-level and album-level metadata; roll back album on failure
        try:
            album_match.apply_metadata()
            for item in album_match.mapping.keys():
                item.store()

            # Apply album-level metadata and persist
            album_match.apply_album_metadata(album)
            album.store()
        except Exception as e:
            log.exception("Failed to apply metadata for items task %s", task_id)
            try:
                album.remove()
            except Exception:
                pass
            task["status"] = "done"
            return jsonify({"error": f"Failed to apply metadata: {e}"}), 500

        # Write tags to files (best-effort; partial failures return warnings)
        warnings = []
        for item in album_match.mapping.keys():
            if not item.try_write():
                path = getattr(item, "path", "") or ""
                if isinstance(path, bytes):
                    path = path.decode("utf-8", errors="replace")
                resolved = _resolve_path(path) if path else path
                log.warning("Failed to write tags for item %d: %s", item.id, resolved)
                warnings.append(f"file write failed: {resolved}")
            else:
                log.info("Wrote tags for item %d: %s", item.id, item.title)

        task.pop("_matches", None)
        task["status"] = "done"
        log.info(
            "Items identify confirm done task=%s album_id=%d warnings=%d",
            task_id,
            album.id,
            len(warnings),
        )

        resp = {"status": "ok", "album_id": album.id}
        if warnings:
            resp["warnings"] = warnings
        return jsonify(resp)

    except Exception as e:
        task["status"] = "done"
        log.exception("Confirm failed for items task %s", task_id)
        return jsonify({"error": str(e)}), 500
    finally:
        if lib is not None:
            lib._close()
