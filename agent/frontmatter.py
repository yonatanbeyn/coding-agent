"""YAML frontmatter parsing shared by skills and agent skills.

Both formats are markdown files that start with a `---` delimited YAML block:

    ---
    name: my-thing
    description: What it is and when to use it.
    ---
    Markdown body…
"""

from pathlib import Path

import yaml


def parse_markdown_with_frontmatter(path: Path) -> tuple[dict, str] | None:
    """Return (frontmatter, body) or None if the file has no valid frontmatter."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None

    return meta, parts[2].strip()


def as_name_list(value) -> list[str] | None:
    """Normalise a tool/skill list field.

    Accepts the comma/space separated string form used by Claude Code
    (`tools: read_file, search_repo`) and the YAML list form used by
    GitHub Copilot (`tools: [read_file, search_repo]`). None means "not set".
    """
    if value is None:
        return None
    if isinstance(value, str):
        return [v for v in value.replace(",", " ").split() if v]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return None
