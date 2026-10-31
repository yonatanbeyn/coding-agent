"""Skills — reusable know-how loaded INTO the agent that is already running.

A skill does not define an agent. It is a folder with a SKILL.md (plus optional
scripts/, reference/, assets/) that teaches whichever agent activates it how to
do one kind of task. Format follows the open Agent Skills spec
(https://agentskills.io), so skills written for Claude Code or GitHub Copilot
work here unchanged.

    skills/desktop-gui/
    ├── SKILL.md
    └── scripts/ …

Progressive disclosure:
  1. Catalog  — only name + description of every skill sits in the system prompt.
  2. Activate — the model calls `activate_skill` to load the SKILL.md body.
  3. Resources — the body points at files the model reads / scripts it runs.

Compare with agent skills (agent/agent_skills.py), which define a whole agent.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from agent.frontmatter import as_name_list, parse_markdown_with_frontmatter

BUNDLED_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# Search order = precedence: project beats user beats bundled.
_PROJECT_DIRS = [".agents/skills", ".claude/skills", ".github/skills"]
_USER_DIRS = ["~/.agents/skills", "~/.claude/skills", "~/.copilot/skills"]

_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass
class Skill:
    name: str
    description: str
    path: Path                  # folder containing SKILL.md
    body: str                   # instructions, loaded into context on activation
    scope: str                  # "project" | "user" | "bundled"
    allowed_tools: list[str] = field(default_factory=list)
    compatibility: str = ""

    def resources(self) -> list[str]:
        """Files bundled with the skill, relative to its folder."""
        return sorted(
            str(p.relative_to(self.path))
            for p in self.path.rglob("*")
            if p.is_file() and p.name != "SKILL.md"
        )


def _search_roots(workspace: str) -> list[tuple[Path, str]]:
    roots = [(Path(workspace) / d, "project") for d in _PROJECT_DIRS]
    roots += [(Path(d).expanduser(), "user") for d in _USER_DIRS]
    roots.append((BUNDLED_SKILLS_DIR, "bundled"))
    return roots


def _parse_skill(skill_md: Path, scope: str) -> tuple[Skill | None, str | None]:
    parsed = parse_markdown_with_frontmatter(skill_md)
    if not parsed:
        return None, f"{skill_md}: missing or invalid YAML frontmatter"
    meta, body = parsed

    name = str(meta.get("name") or "").strip()
    description = str(meta.get("description") or "").strip()
    if not name or not description:
        return None, f"{skill_md}: 'name' and 'description' are required"
    if len(name) > 64 or not _NAME_RE.match(name):
        return None, f"{skill_md}: invalid name {name!r} (lowercase letters, digits, hyphens)"
    # The spec says name should match the folder, but Claude Code and Copilot
    # accept a mismatch, so we do too for compatibility.

    return Skill(
        name=name,
        description=description[:1024],
        path=skill_md.parent,
        body=body,
        scope=scope,
        allowed_tools=as_name_list(meta.get("allowed-tools")) or [],
        compatibility=str(meta.get("compatibility") or ""),
    ), None


def discover_skills(workspace: str) -> tuple[dict[str, Skill], list[str]]:
    """Find all skills. Returns (skills by name, problems found while loading)."""
    skills: dict[str, Skill] = {}
    problems: list[str] = []
    for root, scope in _search_roots(workspace):
        if not root.is_dir():
            continue
        for skill_md in sorted(root.glob("*/SKILL.md")):
            skill, problem = _parse_skill(skill_md, scope)
            if problem:
                problems.append(problem)
            elif skill.name not in skills:
                skills[skill.name] = skill
    return skills, problems


def skills_catalog(skills: dict[str, Skill]) -> str:
    """Level-1 disclosure: one line per skill for the system prompt."""
    if not skills:
        return ""
    lines = [f"- {s.name}: {s.description}" for s in skills.values()]
    return (
        "## Skills\n"
        "Skills are instructions you load into yourself. When a task matches a skill below, "
        "call activate_skill with its name BEFORE starting, then follow its instructions.\n"
        + "\n".join(lines)
    )
