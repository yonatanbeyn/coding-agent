"""File system tools: read, write, list, search."""

import os
import re
import subprocess
from pathlib import Path


def read_file(path: str, workspace: str | None = None) -> dict:
    """Read a text file and return its content."""
    full_path = _resolve(path, workspace)
    try:
        text = Path(full_path).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        # Add line numbers for easier reference
        numbered = "\n".join(f"{i+1:4}: {line}" for i, line in enumerate(lines))
        return {"content": numbered, "lines": len(lines), "path": str(full_path)}
    except FileNotFoundError:
        return {"error": f"File not found: {full_path}"}
    except Exception as e:
        return {"error": str(e)}


def write_file(path: str, content: str, workspace: str | None = None) -> dict:
    """Create or overwrite a file with the given content."""
    full_path = _resolve(path, workspace)
    try:
        Path(full_path).parent.mkdir(parents=True, exist_ok=True)
        Path(full_path).write_text(content, encoding="utf-8")
        lines = len(content.splitlines())
        return {"success": True, "path": str(full_path), "lines_written": lines}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_files(path: str = ".", workspace: str | None = None, max_depth: int = 3) -> dict:
    """List files and directories in a path, respecting .gitignore if present."""
    full_path = _resolve(path, workspace)
    try:
        # Use git ls-files if in a git repo for a cleaner listing
        result = subprocess.run(
            ["git", "ls-files", "--others", "--cached", "--exclude-standard"],
            capture_output=True,
            text=True,
            cwd=str(full_path),
        )
        if result.returncode == 0 and result.stdout.strip():
            files = sorted(result.stdout.strip().splitlines())
            return {"files": files, "count": len(files), "source": "git"}

        # Fallback: walk the directory
        entries = []
        for root, dirs, fnames in os.walk(full_path):
            # Skip hidden dirs and common noise
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__", "target", "build", ".git"}]
            depth = len(Path(root).relative_to(full_path).parts)
            if depth > max_depth:
                dirs.clear()
                continue
            rel = Path(root).relative_to(full_path)
            for fname in fnames:
                entries.append(str(rel / fname) if str(rel) != "." else fname)
        return {"files": sorted(entries), "count": len(entries), "source": "walk"}
    except Exception as e:
        return {"error": str(e)}


def search_repo(pattern: str, path: str = ".", file_glob: str = "*", workspace: str | None = None) -> dict:
    """Search for a regex pattern in files. Returns matching lines with context."""
    full_path = _resolve(path, workspace)
    try:
        cmd = [
            "grep", "-r", "-n", "--include", file_glob,
            "-E", pattern, str(full_path),
            "--max-count=10",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            matches = result.stdout.strip().splitlines()
            # Make paths relative
            rel_matches = [m.replace(str(full_path) + "/", "") for m in matches]
            return {"matches": rel_matches, "count": len(rel_matches)}
        return {"matches": [], "count": 0}
    except Exception as e:
        return {"error": str(e)}


def _resolve(path: str, workspace: str | None) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    if workspace:
        return Path(workspace) / path
    return Path(os.getcwd()) / path


# Schemas

READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the file (relative to workspace or absolute)"},
    },
    "required": ["path"],
}

WRITE_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Destination file path"},
        "content": {"type": "string", "description": "Full file content to write"},
    },
    "required": ["path", "content"],
}

LIST_FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Directory to list. Default: workspace root", "default": "."},
        "max_depth": {"type": "integer", "description": "Max directory depth. Default 3", "default": 3},
    },
}

SEARCH_REPO_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Regex pattern to search for"},
        "path": {"type": "string", "description": "Directory to search in. Default: workspace root", "default": "."},
        "file_glob": {"type": "string", "description": "File name glob filter, e.g. '*.py', '*.java'. Default: all files", "default": "*"},
    },
    "required": ["pattern"],
}