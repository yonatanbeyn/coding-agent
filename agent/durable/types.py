"""Payloads passed between the client, workflows and activities.

Plain dataclasses of JSON-friendly types so Temporal's default data converter
can store them in workflow history. API keys never appear here: activities
read them from the worker's own environment.
"""

from dataclasses import dataclass, field


@dataclass
class AgentInput:
    """Start one agent: the main agent (depth 0) or a sub-agent (agent_skill set)."""
    workspace: str
    provider: str
    model: str
    max_iterations: int
    max_tokens: int
    prompt: str                          # user prompt (main agent) or delegated task (sub-agent)
    base_url: str | None = None
    enable_aws: bool = True
    auto_allow_all: bool = False         # --yes: never wait for approvals
    agent_skill: str | None = None
    depth: int = 0
    callers: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    final_text: str
    steps: int
    input_tokens: int
    output_tokens: int


@dataclass
class SetupRequest:
    workspace: str
    provider: str
    model: str
    max_iterations: int
    base_url: str | None
    enable_aws: bool
    agent_skill: str | None
    depth: int
    callers: list[str]


@dataclass
class SkillInfo:
    scope: str
    allowed_tools: list[str]
    activation: dict                     # tool result returned by activate_skill


@dataclass
class AgentSetupInfo:
    label: str
    model: str
    max_iterations: int
    system_prompt: str                   # base prompt + skill and agent-skill catalogs
    allowed_tools: list[str] | None
    skills: dict[str, SkillInfo]
    agent_skills: dict[str, str]         # name -> scope
    workspace_context: str


@dataclass
class ToolScope:
    """Which tools an agent may use right now — rebuilt into a ToolRegistry by each activity."""
    workspace: str
    enable_aws: bool
    allowed_tools: list[str] | None
    unlocked: list[str]


@dataclass
class LLMRequest:
    provider: str
    model: str
    base_url: str | None
    system: str
    history: list[dict]
    max_tokens: int
    tools: ToolScope
    has_skills: bool
    can_delegate: bool


@dataclass
class LLMResult:
    content: str
    tool_calls: list[dict]               # [{"id", "name", "arguments"}]
    input_tokens: int
    output_tokens: int


@dataclass
class ToolRequest:
    tools: ToolScope
    name: str
    arguments: dict


@dataclass
class ToolOutcome:
    content: str
    is_error: bool


@dataclass
class PendingApproval:
    call_id: str
    tool: str
    arguments: dict


@dataclass
class ApprovalDecision:
    call_id: str
    allow: bool


@dataclass
class ChildInfo:
    workflow_id: str
    agent: str
    done: bool = False


@dataclass
class AgentStatus:
    label: str
    state: str                           # starting | running | waiting_for_approval | done
    events: list[str]                    # events after the `since` index passed to the query
    total_events: int
    pending: list[PendingApproval]
    children: list[ChildInfo]
