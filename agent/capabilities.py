"""What one agent can do: its config, tools, skills and delegation targets.

Shared by the in-process runtime (agent/loop.py) and the durable Temporal
runtime (agent/durable/) so both resolve agent skills, skills and the
skill/delegation meta-tools identically.
"""

from dataclasses import dataclass, replace

from config import Config
from agent.agent_skills import AgentSkill, agent_skills_catalog, discover_agent_skills
from agent.llm.base import ToolDef
from agent.skills import Skill, discover_skills, skills_catalog

# main agent → team lead → workers. Below the top level only agent skills that
# list `delegate_to_agent` in `tools:` can delegate, and never past this depth.
MAX_DEPTH = 2

# Upper bound on sub-agents started by one delegate_parallel call.
MAX_PARALLEL = 5

META_TOOLS = ("activate_skill", "delegate_to_agent", "delegate_parallel")

ACTIVATE_SKILL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Skill name from the Skills catalog"},
    },
    "required": ["name"],
}

_TASK_PROPERTIES = {
    "agent": {"type": "string", "description": "Agent skill name from the Agent skills catalog"},
    "task": {
        "type": "string",
        "description": "Complete, self-contained task. The sub-agent cannot see this conversation.",
    },
}

DELEGATE_SCHEMA = {
    "type": "object",
    "properties": _TASK_PROPERTIES,
    "required": ["agent", "task"],
}

DELEGATE_PARALLEL_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_PARALLEL,
            "items": {"type": "object", "properties": _TASK_PROPERTIES, "required": ["agent", "task"]},
        },
    },
    "required": ["tasks"],
}


@dataclass
class AgentSetup:
    config: Config                       # with the agent skill's prompt/model/max-iterations applied
    agent_skill: AgentSkill | None       # None = the default coding agent
    allowed_tools: list[str] | None      # agent skill `tools:`; None = every tool
    skills: dict[str, Skill]             # skills this agent may activate
    agent_skills: dict[str, AgentSkill]  # agent skills this agent may delegate to
    problems: list[str]                  # files skipped during discovery

    @property
    def system_prompt(self) -> str:
        return compose_system_prompt(self.config.system_prompt, self.skills, self.agent_skills)


def find_agent_skill(workspace: str, name: str) -> AgentSkill:
    found, _ = discover_agent_skills(workspace)
    if name not in found:
        available = ", ".join(sorted(found)) or "none"
        raise ValueError(f"Unknown agent skill {name!r}. Available: {available}")
    return found[name]


def resolve_setup(
    config: Config,
    agent_skill: AgentSkill | None,
    depth: int = 0,
    callers: tuple[str, ...] = (),
) -> AgentSetup:
    """Apply an agent skill to the base config and work out its skills and delegation targets."""
    if agent_skill:
        config = replace(
            config,
            system_prompt=agent_skill.system_prompt,
            model=agent_skill.resolve_model(config.provider, config.model),
            max_iterations=agent_skill.max_iterations or config.max_iterations,
        )
    ws = config.workspace
    allowed_tools = agent_skill.tools if agent_skill else None

    # Skills: know-how this agent can load into itself.
    all_skills, skill_problems = discover_skills(ws)
    wanted = agent_skill.skills if agent_skill else None
    skills = all_skills if wanted is None else {n: s for n, s in all_skills.items() if n in wanted}

    # Agent skills: other agents this agent can delegate to.
    all_agents, agent_problems = discover_agent_skills(ws)
    can_delegate = depth < MAX_DEPTH and (
        agent_skill is None
        or (allowed_tools is not None and "delegate_to_agent" in allowed_tools)
    )
    agent_skills: dict[str, AgentSkill] = {}
    if can_delegate:
        # Never offer an agent itself or a caller up the chain (no A → B → A loops).
        excluded = {agent_skill.name if agent_skill else None, *callers}
        agent_skills = {n: a for n, a in all_agents.items() if n not in excluded}

    return AgentSetup(
        config=config,
        agent_skill=agent_skill,
        allowed_tools=allowed_tools,
        skills=skills,
        agent_skills=agent_skills,
        problems=skill_problems + agent_problems,
    )


def compose_system_prompt(base: str, skills: dict, agent_skills: dict) -> str:
    sections = [base, skills_catalog(skills), agent_skills_catalog(agent_skills)]
    return "\n\n".join(s for s in sections if s)


def meta_tool_defs(has_skills: bool, can_delegate: bool) -> list[ToolDef]:
    """Schemas of the skill / delegation tools. Callers attach `fn` themselves."""
    tools = []
    if has_skills:
        tools.append(ToolDef(
            name="activate_skill",
            description=(
                "Load a skill's full instructions into your context (and unlock the tools it "
                "needs). Call this before working on a task that a listed skill covers."
            ),
            parameters=ACTIVATE_SKILL_SCHEMA,
        ))
    if can_delegate:
        tools.append(ToolDef(
            name="delegate_to_agent",
            description=(
                "Hand a task to an agent skill (a sub-agent with its own instructions, tools and "
                "model). It runs to completion in a separate context and returns its final answer."
            ),
            parameters=DELEGATE_SCHEMA,
        ))
        tools.append(ToolDef(
            name="delegate_parallel",
            description=(
                f"Hand up to {MAX_PARALLEL} INDEPENDENT tasks to agent skills at once and get all "
                "their answers back together. Only use it for tasks that do not depend on each "
                "other or edit the same files; otherwise call delegate_to_agent one at a time."
            ),
            parameters=DELEGATE_PARALLEL_SCHEMA,
        ))
    return tools


def skill_activation_result(skill: Skill) -> dict:
    """The tool result returned to the model when it activates a skill."""
    return {
        "skill": skill.name,
        "base_dir": str(skill.path),
        "instructions": skill.body,
        "resources": skill.resources(),
        "note": "Resource paths are relative to base_dir. Read them or run scripts only when needed.",
    }


def subagent_first_message(workspace_context: str, task: str) -> str:
    return f"Workspace context:\n{workspace_context}\n\nTask:\n{task}"
