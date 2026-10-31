"""Agent skills — markdown files that DEFINE an agent.

Where a skill (agent/skills.py) is know-how loaded into the current agent, an
agent skill is the agent itself: its persona/system prompt, which tools it may
use, which skills it may activate, and optionally its model. The format is
compatible with Claude Code subagents (.claude/agents/*.md) and GitHub Copilot
custom agents (.github/agents/*.agent.md).

    ---
    name: code-reviewer
    description: Reviews diffs for bugs. Use after code changes.
    tools: read_file, search_repo, git_diff   # omit = all tools
    skills: [desktop-gui]                     # omit = all skills, [] = none
    model: inherit                            # or sonnet / opus / haiku / a model id
    max-iterations: 20
    ---
    You are a meticulous code reviewer…   ← the agent's system prompt

An agent skill runs either as the main session (`python main.py --agent NAME`)
or as a sub-agent the main agent delegates to with `delegate_to_agent`. A
sub-agent gets its own conversation, tool allowlist and model, and returns only
its final answer to the caller.
"""

from dataclasses import dataclass
from pathlib import Path

from agent.frontmatter import as_name_list, parse_markdown_with_frontmatter

BUNDLED_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"

# Search order = precedence: project beats user beats bundled.
_PROJECT_DIRS = [".agents/agents", ".claude/agents", ".github/agents"]
_USER_DIRS = ["~/.agents/agents", "~/.claude/agents", "~/.copilot/agents"]

# Claude Code model aliases → Anthropic model ids.
_MODEL_ALIASES = {
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
    "haiku": "claude-haiku-5-5",
}


@dataclass
class AgentSkill:
    name: str
    description: str
    path: Path                      # the .md file
    system_prompt: str              # markdown body
    scope: str                      # "project" | "user" | "bundled"
    tools: list[str] | None = None  # None = every tool
    skills: list[str] | None = None # None = every skill
    model: str | None = None        # None / "inherit" = caller's model
    max_iterations: int | None = None

    def resolve_model(self, provider: str, default: str) -> str:
        if not self.model or self.model == "inherit":
            return default
        if self.model in _MODEL_ALIASES:
            # Aliases only make sense for Anthropic; other providers keep their model.
            return _MODEL_ALIASES[self.model] if provider == "anthropic" else default
        return self.model


def _search_roots(workspace: str) -> list[tuple[Path, str]]:
    roots = [(Path(workspace) / d, "project") for d in _PROJECT_DIRS]
    roots += [(Path(d).expanduser(), "user") for d in _USER_DIRS]
    roots.append((BUNDLED_AGENTS_DIR, "bundled"))
    return roots


def _parse_agent_skill(path: Path, scope: str) -> tuple[AgentSkill | None, str | None]:
    parsed = parse_markdown_with_frontmatter(path)
    if not parsed:
        return None, f"{path}: missing or invalid YAML frontmatter"
    meta, body = parsed

    default_name = path.name.removesuffix(".md").removesuffix(".agent")
    name = str(meta.get("name") or default_name).strip()
    description = str(meta.get("description") or "").strip()
    if not description:
        return None, f"{path}: 'description' is required"
    if not body:
        return None, f"{path}: the body (the agent's system prompt) is empty"

    max_iter = meta.get("max-iterations")
    return AgentSkill(
        name=name,
        description=description,
        path=path,
        system_prompt=body,
        scope=scope,
        tools=as_name_list(meta.get("tools")),
        skills=as_name_list(meta.get("skills")),
        model=str(meta["model"]) if meta.get("model") else None,
        max_iterations=int(max_iter) if max_iter else None,
    ), None


def discover_agent_skills(workspace: str) -> tuple[dict[str, AgentSkill], list[str]]:
    """Find all agent skills. Returns (agent skills by name, problems found)."""
    agents: dict[str, AgentSkill] = {}
    problems: list[str] = []
    for root, scope in _search_roots(workspace):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            agent, problem = _parse_agent_skill(path, scope)
            if problem:
                problems.append(problem)
            elif agent.name not in agents:
                agents[agent.name] = agent
    return agents, problems


def agent_skills_catalog(agents: dict[str, AgentSkill]) -> str:
    """One line per agent skill for the system prompt of the delegating agent."""
    if not agents:
        return ""
    lines = [f"- {a.name}: {a.description}" for a in agents.values()]
    return (
        "## Agent skills (sub-agents)\n"
        "Agent skills are separate agents with their own instructions and tools. When a task "
        "matches one, hand it off with delegate_to_agent(agent, task) and use its answer. "
        "The sub-agent cannot see this conversation, so put everything it needs in `task`.\n"
        + "\n".join(lines)
    )
