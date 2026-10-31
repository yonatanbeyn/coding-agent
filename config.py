"""Configuration for the coding agent."""

import os
from dataclasses import dataclass, field
from typing import Optional


# Generic rules for the default agent. Specialised know-how (GUI automation, AWS, …)
# lives in skills/ and is loaded on demand; whole agents live in agents/.
# Their catalogs are appended to this prompt at runtime (see AgentLoop.system_prompt).
SYSTEM_PROMPT = """You are an expert coding agent. You can read and modify files, run shell commands, manage git repositories, install dependencies and run tests. More capabilities (desktop GUI automation, AWS, …) come from skills you activate, and you can hand whole tasks to specialised sub-agents (agent skills).

Guidelines:
- Read project files only when the task genuinely requires it (e.g. writing/modifying code).
- If a task is ambiguous, ask the user for the missing details before acting — do not guess URLs, endpoints or credentials from the workspace.
- When a skill in the catalog matches the task, activate it first and follow its instructions.
- When an agent skill matches the task, delegate it with a complete, self-contained task description.
- When an error occurs, analyze it and fix it automatically before reporting to the user
- Never run destructive commands (rm -rf, drop database, etc.) without explicit user confirmation
- Work within the provided workspace directory"""


@dataclass
class Config:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_iterations: int = 50
    max_tokens: int = 8192
    workspace: str = field(default_factory=os.getcwd)
    system_prompt: str = SYSTEM_PROMPT
    stream: bool = True
    enable_aws: bool = True
    # Durable runtime (Temporal) — used by --worker, --durable and --attach
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "coding-agent"

    @classmethod
    def from_env(cls) -> "Config":
        provider = os.getenv("AGENT_PROVIDER", "anthropic")

        model_defaults = {
            "anthropic": "claude-sonnet-4-6",
            "openai": "gpt-4o",
            "ollama": "llama3.2",
        }

        api_key = (
            os.getenv("AGENT_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )

        return cls(
            provider=provider,
            model=os.getenv("AGENT_MODEL", model_defaults.get(provider, "claude-sonnet-4-6")),
            api_key=api_key,
            base_url=os.getenv("AGENT_BASE_URL"),
            workspace=os.path.abspath(os.getenv("AGENT_WORKSPACE", os.getcwd())),
            max_iterations=int(os.getenv("AGENT_MAX_ITERATIONS", "50")),
            stream=os.getenv("AGENT_STREAM", "true").lower() == "true",
            temporal_address=os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
            temporal_namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
            temporal_task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "coding-agent"),
        )