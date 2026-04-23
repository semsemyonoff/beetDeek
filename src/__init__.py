"""beetDeek Flask application factory."""

import os

from flask import Flask


def create_app(test_config=None):
    """Create and configure the Flask application.

    Args:
        test_config: Optional dict of config overrides (e.g. LIBRARY_DB for tests).
    """
    app = Flask(__name__, static_folder="static", template_folder="templates")

    app.config["LIBRARY_DB"] = os.environ.get("BEETS_LIBRARY_DB", "/data/beets/library.db")
    app.config["IMPORT_DIR"] = os.environ.get("BEETS_IMPORT_DIR", "/music")
    # LIBRARY_ROOT: base path for resolving relative item/album paths stored by
    # beets 2.10.0. Sourced from beets.library.Library.directory at startup.
    # Empty string means paths are treated as absolute (pre-2.10.0 behaviour).
    app.config["LIBRARY_ROOT"] = os.environ.get("BEETS_LIBRARY_ROOT", "")

    if test_config:
        app.config.update(test_config)

    # Derive LIBRARY_ROOT from beets Library instance if not explicitly configured.
    # Beets 2.10.0 stores all item/artpath values relative to Library.directory.
    # Skip in TESTING mode — test_config provides LIBRARY_ROOT explicitly.
    if (
        not app.config.get("LIBRARY_ROOT")
        and not app.config.get("TESTING")
        and os.path.isfile(app.config.get("LIBRARY_DB", ""))
    ):
        try:
            import beets.library  # noqa: PLC0415

            _lib = beets.library.Library(app.config["LIBRARY_DB"])
            _dir = _lib.directory
            if isinstance(_dir, bytes):
                _dir = _dir.decode("utf-8", errors="replace")
            app.config["LIBRARY_ROOT"] = str(_dir) if _dir else ""
            _lib._close()
        except Exception:
            pass

    from .routes.albums import bp as albums_bp
    from .routes.cover import bp as cover_bp
    from .routes.genres import bp as genres_bp
    from .routes.identify import bp as identify_bp
    from .routes.library import bp as library_bp
    from .routes.lyrics import bp as lyrics_bp
    from .routes.scan import bp as scan_bp

    app.register_blueprint(library_bp)
    app.register_blueprint(albums_bp)
    app.register_blueprint(cover_bp)
    app.register_blueprint(genres_bp)
    app.register_blueprint(identify_bp)
    app.register_blueprint(lyrics_bp)
    app.register_blueprint(scan_bp)

    return app
