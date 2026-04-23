"""Scan routes for beetDeek.

Endpoints:
    POST  /api/rescan         — start library rescan
    GET   /api/rescan/status  — poll rescan status
"""

import shlex
import subprocess
import sys

from flask import Blueprint, current_app, jsonify, request

from src import state
from src.utils import _get_ro_conn, log

bp = Blueprint("scan", __name__)


# ---------------------------------------------------------------------------
# Private helpers (scan-specific)
# ---------------------------------------------------------------------------


def _take_snapshot():
    """Snapshot current items {id: (title, artist, album_id)} from the DB."""
    try:
        conn = _get_ro_conn()
        rows = conn.execute("SELECT id, title, artist, album_id FROM items").fetchall()
        conn.close()
        return {r["id"]: (r["title"], r["artist"], r["album_id"]) for r in rows}
    except Exception:
        return {}


def _compute_scan_diff(before, after):
    """Compare snapshots and return added/removed lists."""
    before_ids = set(before.keys())
    after_ids = set(after.keys())
    added = []
    for item_id in sorted(after_ids - before_ids):
        title, artist, _ = after[item_id]
        added.append({"id": item_id, "title": title, "artist": artist})
    removed = []
    for item_id in sorted(before_ids - after_ids):
        title, artist, _ = before[item_id]
        removed.append({"id": item_id, "title": title, "artist": artist})
    return added, removed


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@bp.route("/api/rescan", methods=["POST"])
def rescan():
    mode = request.args.get("mode", "quick")
    if mode not in {"quick", "full"}:
        return jsonify({"error": f"Invalid mode: {mode!r}. Must be 'quick' or 'full'"}), 400
    import_dir = current_app.config["IMPORT_DIR"]
    with state.rescan_lock:
        if state.rescan_proc and state.rescan_proc.poll() is None:
            return jsonify({"status": "running"}), 409
        state.rescan_snapshot = _take_snapshot()
        inc = "-i" if mode == "quick" else "-I"
        cmd = f"beet -v import -A -C {inc} {shlex.quote(import_dir)} && beet -v update -M"
        log.info("Starting rescan (%s): %s", mode, cmd)
        state.rescan_proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
    return jsonify({"status": "started", "mode": mode})


@bp.route("/api/rescan/status")
def rescan_status():
    with state.rescan_lock:
        proc = state.rescan_proc
        snapshot = state.rescan_snapshot
    if proc is None:
        return jsonify({"status": "idle"})
    if proc.poll() is None:
        return jsonify({"status": "running"})
    # Process finished: compute diff, then clear state so future polls return
    # "idle" and repeated calls don't re-query the entire DB each time.
    result = {"status": "done", "returncode": proc.returncode}
    if snapshot is not None:
        after = _take_snapshot()
        added, removed = _compute_scan_diff(snapshot, after)
        result["added"] = added
        result["removed"] = removed
    with state.rescan_lock:
        # Only clear if no new rescan was started between our two lock acquisitions.
        if state.rescan_proc is proc:
            state.rescan_proc = None
            state.rescan_snapshot = None
    return jsonify(result)
