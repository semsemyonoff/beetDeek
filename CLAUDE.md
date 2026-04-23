# beetDeek — Claude Code Project Documentation

## Project Overview

beetDeek is a web UI for browsing and managing a [beets](https://beets.io) music library. It provides album browsing, cover art management, genre editing, lyrics fetching, MusicBrainz identification, and library rescanning — all via a Flask-based REST API consumed by a vanilla JS SPA.

## Tech Stack

- **Backend**: Python 3.14, Flask, gunicorn (1 worker, 4 threads)
- **Database**: SQLite (beets library.db), accessed read-only via direct SQL for most queries; beets Library object used for write operations
- **Key dependencies**: beets==2.10.0, Pillow, pylast (Last.fm), requests, beautifulsoup4, pyacoustid
- **Frontend**: Vanilla JS SPA (hash routing) in `src/templates/index.html`, JS split into `src/static/js/` modules
- **Container**: Docker (`python:3.14-slim`), ffmpeg installed for audio fingerprinting

## Project Structure

```
beetDeek/
├── app.py                  # Thin entry point: calls create_app() from src/
├── src/
│   ├── __init__.py         # Flask app factory (create_app)
│   ├── state.py            # Shared in-memory state (globals)
│   ├── utils.py            # Shared helpers and constants
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── library.py      # GET /, /api/library, /api/search, /api/artist
│   │   ├── albums.py       # GET /api/album/<id>, /api/album/<id>/track/<id>/tags
│   │   ├── cover.py        # Cover art CRUD
│   │   ├── genres.py       # Genre fetch/confirm/save
│   │   ├── lyrics.py       # Lyrics CRUD (single + bulk)
│   │   ├── identify.py     # Identify/status/apply/confirm
│   │   └── scan.py         # Rescan + status
│   ├── static/
│   │   ├── style.css
│   │   ├── logo.svg
│   │   └── js/             # Frontend JS split by feature area
│   │       ├── routing.js
│   │       ├── library.js
│   │       ├── album.js
│   │       ├── artist.js
│   │       ├── cover.js
│   │       ├── genres.js
│   │       ├── lyrics.js
│   │       ├── identify.js
│   │       ├── scan.js
│   │       ├── search.js
│   │       ├── filter.js
│   │       ├── theme.js
│   │       └── utils.js
│   └── templates/
│       └── index.html      # Frontend SPA shell (loads JS modules from src/static/js/)
├── tests/
│   ├── conftest.py         # Fixtures: create_app with temp SQLite DB, schema helpers
│   ├── test_db_fixture.py
│   ├── test_utils.py
│   ├── test_library.py
│   ├── test_albums.py
│   ├── test_cover.py
│   ├── test_genres.py
│   ├── test_lyrics.py
│   ├── test_identify.py
│   └── test_scan.py
├── constraints.txt         # beets version pin (single source of truth)
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Test/lint tools (pytest, pytest-cov, ruff)
├── pyproject.toml          # pytest and ruff configuration
├── Dockerfile
├── Makefile
├── build.sh
├── config.yaml             # Beets configuration example
└── docs/
    └── plans/              # Implementation plans
```

### In-Memory State (src/state.py)

The application uses module-level globals for shared state across request threads:

- `rescan_lock` (threading.Lock) — guards scan process access
- `rescan_proc` (subprocess.Popen | None) — running beet import/scan subprocess
- `rescan_snapshot` (dict | None) — item snapshot `{id: (title, artist, album_id)}` taken before scan starts
- `identify_tasks` (dict) — background autotag tasks keyed by album_id; cover previews stored under `f"cover_{album_id}"` keys
- `identify_lock` (threading.Lock) — guards identify task access

### Key Config (app.config via create_app)

- `LIBRARY_DB` — path to beets SQLite database (env: `BEETS_LIBRARY_DB`, default: `/data/beets/library.db`)
- `IMPORT_DIR` — path to music import directory (env: `BEETS_IMPORT_DIR`, default: `/music`)
- `LIBRARY_ROOT` — beets library directory for resolving relative paths (env: `BEETS_LIBRARY_ROOT`; auto-detected from beets Library at startup)

### API Routes

- `GET /` — serves SPA
- `GET /api/library` — album list
- `GET /api/search` — search albums/artists
- `GET /api/artist` — artist albums
- `GET /api/album/<id>` — album detail with tracks
- `GET /api/album/<id>/track/<id>/tags` — track tags
- `GET /api/album/<id>/cover` — serve current cover image
- `POST /api/album/<id>/cover/fetch` — fetch cover from online sources (preview)
- `GET /api/album/<id>/cover/preview` — serve fetched cover preview
- `POST /api/album/<id>/cover/confirm` — confirm and save fetched cover
- `POST /api/album/<id>/cover/upload` — upload cover image
- `POST /api/album/<id>/genre` — fetch genre from Last.fm (preview)
- `POST /api/album/<id>/genre/confirm` — confirm and write fetched genre
- `POST /api/album/<id>/genre/save` — manually save genre
- `GET /api/album/<id>/track/<id>/lyrics` — get track lyrics
- `POST /api/album/<id>/track/<id>/lyrics/fetch` — fetch lyrics from online (preview)
- `POST /api/album/<id>/track/<id>/lyrics/confirm` — confirm and write fetched lyrics
- `POST /api/album/<id>/track/<id>/lyrics/embed` — embed .lrc file into track
- `POST /api/album/<id>/track/<id>/lyrics/save` — manually save lyrics
- `POST /api/album/<id>/lyrics/fetch` — bulk fetch lyrics for all tracks
- `POST /api/album/<id>/lyrics/confirm` — bulk confirm lyrics for selected tracks
- `POST /api/album/<id>/lyrics/embed` — bulk embed .lrc files for all tracks
- `POST /api/album/<id>/identify` — start background identification
- `GET /api/album/<id>/identify/status` — poll identification status
- `POST /api/album/<id>/apply` — preview diff for a candidate
- `POST /api/album/<id>/confirm` — write chosen candidate tags to files/DB
- `POST /api/rescan` — start library rescan
- `GET /api/rescan/status` — rescan status

## Architecture Constraints

**CRITICAL: Single gunicorn worker required.** The application relies on module-level in-memory globals (`rescan_proc`, `identify_tasks`, etc.) in `src/state.py` for state shared across request threads. Using multiple workers would give each worker its own memory space, causing state to be siloed per-worker and breaking background task tracking (identify jobs, scan status). The gunicorn invocation must always use `-w 1` with `--threads N`.

## App Factory Pattern

Routes are registered via Flask Blueprints in `create_app()` (src/__init__.py). All route modules read config from `current_app.config` rather than module-level constants. Tests use `create_app(test_config={"LIBRARY_DB": "<tmp>", ...})` to inject a temporary SQLite file.

The `_init_beets()` helper in `src/utils.py` accepts an explicit `library_db` parameter rather than reading from `current_app.config`, because it is called from background threads (identify tasks) that have no Flask app context.

## Dev Commands

```bash
# Install dependencies
pip install -r requirements.txt -c constraints.txt
pip install -r requirements-dev.txt

# Run tests
make test

# Lint
make lint

# Format
make fmt

# Test coverage report
make coverage

# Build and push multi-arch Docker image
make build
```

## Beets Version

- **Current**: `beets==2.10.0` (pinned via `constraints.txt`)
- Key 2.10.0 behaviors this app handles:
  - Genres stored as native list field (`genres`); `_format_genre()` in `src/utils.py` handles both list and legacy string values
  - Library paths stored relative to DB root; `_resolve_path()` in `src/utils.py` joins `LIBRARY_ROOT` + relative path (absolute paths pass through unchanged)
  - Lyrics plugin: separate `lyrics_backend`/`lyrics_url`/`lyrics_language` fields (no "Source: URL" suffix in lyrics text)

## Testing

- **Framework**: pytest + pytest-cov + ruff
- **Test structure**: `tests/` at project root, files mirror `src/routes/`
- **Config**: `pyproject.toml`
- **Fixtures**: `tests/conftest.py` — Flask app fixture via `create_app(test_config=...)` with temp SQLite file seeded with beets schema tables
- **Coverage target**: 80%+ for modular code

```bash
make test      # run pytest
make coverage  # run pytest with coverage report
make lint      # ruff check
make fmt       # ruff format
```
