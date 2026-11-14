#!/usr/bin/env python3
"""PreToolUse hook: deploy.sh targets the real production host, so neither editing nor running it
may happen without an explicit human "yes" (CLAUDE.md). Returns permissionDecision "ask": an
interactive session shows a confirmation prompt; a non-interactive run (GitHub Action) cannot
answer it and therefore does not proceed."""
import json
import re
import sys

try:
    event = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)

tool = event.get("tool_name", "")
tool_input = event.get("tool_input") or {}

hit = False
if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    hit = path == "deploy.sh" or path.endswith("/deploy.sh")
elif tool == "Bash":
    hit = re.search(r"(^|[\s;&|/])deploy\.sh\b", str(tool_input.get("command") or "")) is not None

if hit:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "deploy.sh deployt auf den echten Produktionshost - nur nach ausdrücklicher Bestätigung.",
        }
    }))
sys.exit(0)
