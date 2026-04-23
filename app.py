"""beetDeek entry point — thin wrapper around the src app factory."""
from src import create_app

app = create_app()
