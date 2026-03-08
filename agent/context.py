"""Context builder — injects repo state into the agent's first message."""

import os
import subprocess
from pathlib import Path


def build_context(workspace: str) -> str:
    """Build a context string about the workspace to include at session start."""
    parts = []

    parts.append(f"Workspace: {workspace}")
    parts.append(f"OS: {_detect_os()}")

    # Git info
    git_status = _run_git(["status", "--short", "--branch"], workspace)
    if git_status:
        parts.append(f"\nGit status:\n{git_status}")

    # Repo tree (top-level)
    tree = _repo_tree(workspace)
    if tree:
        parts.append(f"\nProject structure:\n{tree}")

    return "\n".join(parts)


def _run_git(args: list[str], cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _repo_tree(workspace: str, max_depth: int = 2) -> str:
    """Generate a compact directory tree."""
    # Prefer `tree` command
    try:
        result = subprocess.run(
            ["tree", "-L", str(max_depth), "--gitignore", "-I",
             "node_modules|__pycache__|.git|target|build|.venv|dist"],
            capture_output=True,
            text=True,
            cwd=workspace,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass

    # Fallback: manual walk
    lines = []
    base = Path(workspace)
    skip = {".git", "node_modules", "__pycache__", "target", "build", ".venv", "dist"}

    def walk(path: Path, depth: int, prefix: str = "") -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        for i, entry in enumerate(entries):
            if entry.name.startswith(".") or entry.name in skip:
                continue
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if i == len(entries) - 1 else "│   "
                walk(entry, depth + 1, prefix + extension)

    walk(base, 0)
    return "\n".join(lines[:80])  # cap at 80 lines


def _detect_os() -> str:
    import platform
    s = platform.system()
    if s == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    if s == "Linux":
        return f"Linux ({platform.release()})"
    if s == "Windows":
        return f"Windows {platform.version()}"
    return s