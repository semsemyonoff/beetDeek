"""Tests for src/utils.py shared helpers."""
import sqlite3

import pytest

from src import create_app
from src.utils import (
    _album_dir_from_items,
    _decode_path,
    _find_cover,
    _format_genre,
    _remove_cover_files,
)

# ---------------------------------------------------------------------------
# _decode_path
# ---------------------------------------------------------------------------


def test_decode_path_bytes():
    assert _decode_path(b"/music/track.mp3") == "/music/track.mp3"


def test_decode_path_str():
    assert _decode_path("/music/track.mp3") == "/music/track.mp3"


def test_decode_path_none():
    assert _decode_path(None) == ""


def test_decode_path_empty_string():
    assert _decode_path("") == ""


def test_decode_path_invalid_utf8():
    result = _decode_path(b"\xff\xfe/music")
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _format_genre
# ---------------------------------------------------------------------------


def test_format_genre_plain_string():
    assert _format_genre("Rock") == "Rock"


def test_format_genre_list():
    assert _format_genre(["Rock", "Pop"]) == "Rock, Pop"


def test_format_genre_tuple():
    assert _format_genre(("Jazz", "Blues")) == "Jazz, Blues"


def test_format_genre_null_byte_separator():
    assert _format_genre("Rock\x00Pop") == "Rock, Pop"


def test_format_genre_unicode_null_separator():
    assert _format_genre("Rock\u2400Pop") == "Rock, Pop"


def test_format_genre_empty():
    assert _format_genre("") == ""


def test_format_genre_none():
    assert _format_genre(None) == ""


def test_format_genre_bytes():
    assert _format_genre(b"Rock") == "Rock"


def test_format_genre_strips_whitespace():
    assert _format_genre("  Rock  \x00  Pop  ") == "Rock, Pop"


# ---------------------------------------------------------------------------
# _find_cover
# ---------------------------------------------------------------------------


def test_find_cover_finds_cover_jpg(tmp_path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"fake")
    result = _find_cover(str(tmp_path))
    assert result == str(cover)


def test_find_cover_finds_folder_jpg(tmp_path):
    cover = tmp_path / "folder.jpg"
    cover.write_bytes(b"fake")
    result = _find_cover(str(tmp_path))
    assert result == str(cover)


def test_find_cover_returns_none_when_no_cover(tmp_path):
    result = _find_cover(str(tmp_path))
    assert result is None


def test_find_cover_returns_none_for_nonexistent_dir():
    result = _find_cover("/nonexistent/path")
    assert result is None


def test_find_cover_returns_none_for_none():
    result = _find_cover(None)
    assert result is None


def test_find_cover_prefers_cover_jpg_over_folder_jpg(tmp_path):
    (tmp_path / "folder.jpg").write_bytes(b"folder")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    result = _find_cover(str(tmp_path))
    assert result == str(cover)


# ---------------------------------------------------------------------------
# _remove_cover_files
# ---------------------------------------------------------------------------


def test_remove_cover_files_removes_cover_jpg(tmp_path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"fake")
    _remove_cover_files(str(tmp_path))
    assert not cover.exists()


def test_remove_cover_files_removes_folder_png(tmp_path):
    cover = tmp_path / "folder.png"
    cover.write_bytes(b"fake")
    _remove_cover_files(str(tmp_path))
    assert not cover.exists()


def test_remove_cover_files_leaves_non_cover_images(tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"fake")
    _remove_cover_files(str(tmp_path))
    assert img.exists()


def test_remove_cover_files_removes_numbered_variants(tmp_path):
    cover = tmp_path / "cover.1.jpg"
    cover.write_bytes(b"fake")
    _remove_cover_files(str(tmp_path))
    assert not cover.exists()


def test_remove_cover_files_noop_on_nonexistent_dir():
    _remove_cover_files("/nonexistent/path")


def test_remove_cover_files_noop_on_none():
    _remove_cover_files(None)


# ---------------------------------------------------------------------------
# _album_dir_from_items (requires app context for _get_ro_conn)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _app_with_db(tmp_path):
    """App fixture for utils tests that need an app context."""
    db = tmp_path / "library.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE albums (
            id INTEGER PRIMARY KEY, album TEXT, albumartist TEXT,
            genre TEXT, year INTEGER, artpath BLOB
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, path BLOB, album_id INTEGER,
            title TEXT, artist TEXT, track INTEGER, length REAL, format TEXT
        );
        CREATE TABLE album_attributes (id INTEGER, key TEXT, value TEXT, PRIMARY KEY (id, key));
        CREATE TABLE item_attributes (id INTEGER, key TEXT, value TEXT, PRIMARY KEY (id, key));
        """
    )
    conn.commit()
    conn.close()
    return create_app(test_config={"LIBRARY_DB": str(db), "TESTING": True}), str(db)


def test_album_dir_from_items_returns_dir(_app_with_db, tmp_path):
    app, db_path = _app_with_db
    music_dir = tmp_path / "music" / "album"
    music_dir.mkdir(parents=True)
    track_path = str(music_dir / "track.mp3").encode()

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO albums (id, album, albumartist) VALUES (1, 'A', 'B')"
    )
    conn.execute(
        "INSERT INTO items (id, path, album_id, title) VALUES (1, ?, 1, 'T')",
        (track_path,),
    )
    conn.commit()
    conn.close()

    with app.app_context():
        ro_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        ro_conn.row_factory = sqlite3.Row
        result = _album_dir_from_items(ro_conn, 1)
        ro_conn.close()

    assert result == str(music_dir)


def test_album_dir_from_items_returns_none_for_missing(_app_with_db):
    app, db_path = _app_with_db
    with app.app_context():
        ro_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        ro_conn.row_factory = sqlite3.Row
        result = _album_dir_from_items(ro_conn, 999)
        ro_conn.close()
    assert result is None


# ---------------------------------------------------------------------------
# create_app — factory smoke tests
# ---------------------------------------------------------------------------


def test_create_app_default_config():
    app = create_app()
    assert app.config["LIBRARY_DB"] == "/data/beets/library.db"
    assert app.config["IMPORT_DIR"] == "/music"


def test_create_app_test_config(tmp_path):
    db = str(tmp_path / "test.db")
    app = create_app(test_config={"LIBRARY_DB": db, "IMPORT_DIR": "/tmp/music"})
    assert app.config["LIBRARY_DB"] == db
    assert app.config["IMPORT_DIR"] == "/tmp/music"


def test_create_app_returns_flask_app():
    from flask import Flask

    app = create_app()
    assert isinstance(app, Flask)
