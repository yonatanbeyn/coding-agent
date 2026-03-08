"""Git tools."""

import subprocess
from pathlib import Path


def _git(args: list[str], cwd: str) -> dict:
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return {
        "output": (result.stdout + result.stderr).strip(),
        "exit_code": result.returncode,
        "success": result.returncode == 0,
    }


def git_status(workspace: str) -> dict:
    """Show working tree status."""
    return _git(["status", "--short", "--branch"], workspace)


def git_diff(workspace: str, staged: bool = False, path: str | None = None) -> dict:
    """Show diff of unstaged (or staged) changes."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    if path:
        args += ["--", path]
    return _git(args, workspace)


def git_add(workspace: str, files: list[str]) -> dict:
    """Stage files for commit."""
    return _git(["add"] + files, workspace)


def git_commit(workspace: str, message: str) -> dict:
    """Create a commit with the given message."""
    return _git(["commit", "-m", message], workspace)


def git_log(workspace: str, n: int = 10) -> dict:
    """Show last N commits."""
    return _git(["log", f"-{n}", "--oneline", "--graph"], workspace)


def git_init(workspace: str) -> dict:
    """Initialize a new git repository."""
    return _git(["init"], workspace)


def git_clone(url: str, dest: str, workspace: str) -> dict:
    """Clone a repository."""
    return _git(["clone", url, dest], workspace)


# Schemas

GIT_STATUS_SCHEMA = {
    "type": "object",
    "properties": {},
}

GIT_DIFF_SCHEMA = {
    "type": "object",
    "properties": {
        "staged": {"type": "boolean", "description": "Show staged changes. Default: false (unstaged)", "default": False},
        "path": {"type": "string", "description": "Limit diff to specific file/directory"},
    },
}

GIT_ADD_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of file paths to stage. Use ['.'] to stage all.",
        }
    },
    "required": ["files"],
}

GIT_COMMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "description": "Commit message"},
    },
    "required": ["message"],
}

GIT_LOG_SCHEMA = {
    "type": "object",
    "properties": {
        "n": {"type": "integer", "description": "Number of commits to show. Default 10", "default": 10},
    },
}

GIT_CLONE_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "Repository URL to clone"},
        "dest": {"type": "string", "description": "Destination directory name"},
    },
    "required": ["url"],
}