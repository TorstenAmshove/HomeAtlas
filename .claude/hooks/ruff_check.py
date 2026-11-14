#!/usr/bin/env python3
"""PostToolUse hook: lint each edited backend Python file with the repo's ruff config
(backend/ruff.toml) and feed remaining errors back to Claude (exit code 2), so they are fixed in
the same turn instead of surfacing later in CI. Auto-fixes what ruff can fix safely. Silently does
nothing if ruff is not installed (`pip install -r backend/requirements-dev.txt`)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    event = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)

path = Path(str((event.get("tool_input") or {}).get("file_path") or ""))
if path.suffix != ".py" or "backend" not in path.parts or not path.exists():
    sys.exit(0)

ruff = shutil.which("ruff")
if ruff is None:
    sys.exit(0)

# Walk up to the backend/ directory so ruff picks up backend/ruff.toml.
backend = None
for parent in path.resolve().parents:
    if parent.name == "backend":
        backend = parent
        break
if backend is None:
    sys.exit(0)

result = subprocess.run(
    [ruff, "check", "--fix", "--quiet", str(path.resolve())],
    cwd=backend, capture_output=True, text=True, timeout=60,
)
if result.returncode != 0:
    print(f"ruff meldet Fehler in {path}:\n{result.stdout}{result.stderr}", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
