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

    # Blueprints are registered in subsequent tasks (4-10).

    return app
