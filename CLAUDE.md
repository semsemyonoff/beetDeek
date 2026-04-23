# beetDeek — Claude Code Project Documentation

## Project Overview

beetDeek is a web UI for browsing and managing a [beets](https://beets.io) music library. It provides album browsing, cover art management, genre editing, lyrics fetching, MusicBrainz identification, and library rescanning — all via a Flask-based REST API consumed by a vanilla JS SPA.

## Tech Stack

- **Backend**: Python 3.14, Flask, gunicorn (1 worker, 4 threads)
- **Database**: SQLite (beets library.db), accessed read-only via direct SQL for most queries; beets Library object used for write operations
- **Key dependencies**: beets, Pillow, pylast (Last.fm), requests, beautifulsoup4, pyacoustid
- **Frontend**: Vanilla JS SPA (hash routing), inline in `templates/index.html`
- **Container**: Docker (`python:3.14-slim`), ffmpeg installed for audio fingerprinting

## Current Monolithic Structure

```
beetDeek/
├── app.py              # Entire backend: routes, helpers, state (~1680 lines, ~53KB)
├── templates/
│   └── index.html      # Frontend SPA (~1500 lines, vanilla JS with hash routing)
├── static/
│   ├── style.css       # ~21KB
│   └── logo.svg
├── Dockerfile
├── Makefile
├── build.sh
├── config.yaml         # Beets configuration
└── docs/
    └── plans/          # Implementation plans
```

### In-Memory State (app.py:26-30)

The application uses module-level globals for shared state across request threads:

- `_rescan_lock` (threading.Lock) — guards scan process access
- `_rescan_proc` (subprocess.Popen | None) — running beet import/scan subprocess
- `_rescan_snapshot` (dict | None) — item snapshot `{id: (title, artist, album_id)}` taken before scan starts
- `_identify_tasks` (dict) — background autotag tasks keyed by album_id; cover previews stored under `f"cover_{album_id}"` keys
- `_identify_lock` (threading.Lock) — guards identify task access

### Key Constants and Config

- `LIBRARY_DB` — path to beets SQLite database (env: `BEETS_LIBRARY_DB`, default: `/data/beets/library.db`)
- `IMPORT_DIR` — path to music import directory (env: `BEETS_IMPORT_DIR`, default: `/music`)
- `COVER_NAMES` — ordered list of cover art filenames to look for
- `_COVER_STEMS`, `_IMAGE_EXTS` — used for cover file cleanup

### API Routes

- `GET /` — serves SPA
- `GET /api/library` — album list
- `GET /api/search` — search albums/artists
- `GET /api/artist` — artist albums
- `GET /api/album/<id>` — album detail with tracks
- `GET /api/album/<id>/track/<id>/tags` — track tags
- `GET|POST /api/album/<id>/cover` — cover art get/fetch
- `GET /api/album/<id>/cover/preview` — cover preview
- `POST /api/album/<id>/cover/confirm` — confirm cover
- `POST /api/album/<id>/cover/upload` — upload cover
- `GET|POST /api/album/<id>/genre` — genre get/fetch
- `POST /api/album/<id>/genre/confirm` — confirm genre
- `GET|POST /api/album/<id>/lyrics` — lyrics get/fetch (single track)
- `POST /api/album/<id>/lyrics/confirm` — confirm lyrics
- `POST /api/album/<id>/lyrics/embed` — embed lyrics
- `POST /api/album/<id>/lyrics/save` — save lyrics
- `POST /api/album/<id>/lyrics/bulk` — bulk fetch lyrics
- `POST /api/album/<id>/identify` — start identification
- `GET /api/album/<id>/identify/status` — identification status
- `POST /api/album/<id>/identify/apply` — apply identification
- `POST /api/album/<id>/identify/confirm` — confirm identification
- `POST /api/rescan` — start library rescan
- `GET /api/rescan/status` — rescan status

## Target Modular Structure (Refactoring Goal)

```
src/
├── __init__.py          # Flask app factory (create_app)
├── state.py             # Shared in-memory state (extracted globals)
├── utils.py             # Shared helpers and constants
├── routes/
│   ├── __init__.py
│   ├── library.py       # GET /, /api/library, /api/search, /api/artist
│   ├── albums.py        # GET /api/album/<id>, /api/album/<id>/track/<id>/tags
│   ├── cover.py         # Cover art CRUD
│   ├── genres.py        # Genre fetch/confirm/save
│   ├── lyrics.py        # Lyrics CRUD (single + bulk)
│   ├── identify.py      # Identify/status/apply/confirm
│   └── scan.py          # Rescan + status
├── static/              # Moved from root
│   ├── style.css
│   └── logo.svg
└── templates/           # Moved from root
    └── index.html
```

The root `app.py` becomes a thin entry point calling `create_app()` from `src/`.

## Architecture Constraints

**CRITICAL: Single gunicorn worker required.** The application relies on module-level in-memory globals (`_rescan_proc`, `_identify_tasks`, etc.) for state shared across request threads. Using multiple workers would give each worker its own memory space, causing state to be siloed per-worker and breaking background task tracking (identify jobs, scan status). The gunicorn invocation must always use `-w 1` with `--threads N`.

## Dev Commands

```bash
# Build and push multi-arch Docker image
make build

# (After Task 2 tooling is added:)
make test      # Run pytest
make lint      # Run ruff check
make fmt       # Run ruff format
make coverage  # Run pytest with coverage report
```

## Beets Version

- Currently: `beets==2.8.0`
- Target: `beets==2.10.0` (Task 12 in the refactoring plan)
- Version is pinned in `constraints.txt` (single source of truth after Task 2)
- Key 2.10.0 changes affecting this app:
  - Genres stored as native list field (`genres`), no more null-byte separators
  - Library paths stored relative to DB root (requires `LIBRARY_ROOT` resolution)
  - Lyrics plugin: separate `lyrics_backend`/`lyrics_url`/`lyrics_language` fields

## Testing

- No tests exist yet (added in Task 2 of refactoring plan)
- Target: pytest + pytest-cov + ruff, configured in `pyproject.toml`
- Test structure: `tests/` at project root, mirroring `src/routes/`
- Coverage target: 80%+ for new modular code
- Fixture: shared Flask app fixture with temp SQLite file (not `:memory:` — routes check `os.path.isfile(LIBRARY_DB)`)

## Refactoring Plan

See `docs/plans/2026-04-23-migration-and-refactoring.md` for the full 15-task plan covering:
1. CLAUDE.md creation (this file)
2. Test and lint tooling bootstrap
3. `src/` package with app factory
4-10. Blueprint extraction (library, albums, cover, genres, lyrics, identify, scan)
11. Entry point cleanup and static/template moves
12. beets 2.10.0 migration
13. Frontend JS split (if needed)
14. Acceptance verification
15. Documentation update
