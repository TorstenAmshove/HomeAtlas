"""Release version of the running backend.

Set by the image build (`ARG HOMEATLAS_VERSION`, passed by release.yml) and read from the
environment; local and PR builds have none and report "dev"."""
from __future__ import annotations

import os


def app_version() -> str:
    return os.environ.get("HOMEATLAS_VERSION", "").strip() or "dev"
