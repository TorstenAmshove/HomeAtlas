"""HTTP route modules, one per capability group; main.py includes them in a fixed order."""
from . import accounts, auth, chat, diagnostics, docs, overview, scans, settings, systems  # noqa: F401
