"""Session persistence — remembers workspace across runs."""

import json
import os
from pathlib import Path

_SESSION_FILE = Path.home() / ".coding-agent" / "session.json"


def load_last_workspace() -> str | None:
    """Return the last used workspace path, or None if never saved."""
    try:
        data = json.loads(_SESSION_FILE.read_text())
        path = data.get("workspace")
        if path and os.path.isdir(path):
            return path
    except Exception:
        pass
    return None


def save_workspace(workspace: str) -> None:
    """Persist the current workspace so the next run picks it up."""
    try:
        _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        if _SESSION_FILE.exists():
            existing = json.loads(_SESSION_FILE.read_text())
        existing["workspace"] = workspace
        _SESSION_FILE.write_text(json.dumps(existing, indent=2))
    except Exception:
        pass