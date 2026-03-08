"""Configuration for the coding agent."""

import os
from dataclasses import dataclass, field
from typing import Optional


SYSTEM_PROMPT = """You are an expert coding agent. You can read and modify files, run shell commands,
manage git repositories, install dependencies, and interact with AWS services.

Guidelines:
- Always check if required tools/commands exist before using them (use check_command_exists)
- Read files before modifying them (use read_file first)
- Run tests after making significant changes
- Use git_status to understand repo state before committing
- When an error occurs, analyze it and fix it automatically before reporting to the user
- Prefer specific tools over run_shell when available
- Never run destructive commands (rm -rf, drop database, etc.) without explicit user confirmation
- Work within the provided workspace directory

Available tools: run_shell, write_file, read_file, list_files, search_repo,
git_status, git_diff, git_add, git_commit, git_log,
check_command_exists, install_dependency, install_maven, install_node,
run_tests, list_s3_buckets, get_aws_billing"""


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
        )