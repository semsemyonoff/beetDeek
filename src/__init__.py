"""beetDeek Flask application factory."""
import os

from flask import Flask


def create_app(test_config=None):
    """Create and configure the Flask application.

    Args:
        test_config: Optional dict of config overrides (e.g. LIBRARY_DB for tests).
    """
    app = Flask(__name__, static_folder="static", template_folder="templates")

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
    from .routes.scan import bp as scan_bp

    app.register_blueprint(library_bp)
    app.register_blueprint(albums_bp)
    app.register_blueprint(cover_bp)
    app.register_blueprint(genres_bp)
    app.register_blueprint(identify_bp)
    app.register_blueprint(lyrics_bp)
    app.register_blueprint(scan_bp)

    return app
