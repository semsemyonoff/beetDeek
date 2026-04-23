"""beetDeek Flask application factory."""
import os

from flask import Flask

# Root of the repo (one level up from this package).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app(test_config=None):
    """Create and configure the Flask application.

    Args:
        test_config: Optional dict of config overrides (e.g. LIBRARY_DB for tests).
    """
    # Until Task 11 moves static/templates into src/, use the repo-root copies.
    app = Flask(
        __name__,
        static_folder=os.path.join(_REPO_ROOT, "static"),
        template_folder=os.path.join(_REPO_ROOT, "templates"),
    )

    app.config["LIBRARY_DB"] = os.environ.get(
        "BEETS_LIBRARY_DB", "/data/beets/library.db"
    )
    app.config["IMPORT_DIR"] = os.environ.get("BEETS_IMPORT_DIR", "/music")

    if test_config:
        app.config.update(test_config)

    from .routes.library import bp as library_bp
    from .routes.albums import bp as albums_bp
    from .routes.cover import bp as cover_bp
    from .routes.genres import bp as genres_bp
    from .routes.identify import bp as identify_bp
    from .routes.lyrics import bp as lyrics_bp

    app.register_blueprint(library_bp)
    app.register_blueprint(albums_bp)
    app.register_blueprint(cover_bp)
    app.register_blueprint(genres_bp)
    app.register_blueprint(identify_bp)
    app.register_blueprint(lyrics_bp)

    return app
