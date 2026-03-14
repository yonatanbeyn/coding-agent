"""Configuration for the coding agent."""

import os
from dataclasses import dataclass, field
from typing import Optional


SYSTEM_PROMPT = """You are an expert coding agent with full GUI automation capabilities. You can read and modify files, run shell commands, manage git repositories, install dependencies, interact with AWS services, and control the desktop (open apps, take screenshots, click, type, find UI elements with vision).

Guidelines:
- Read project files only when the task genuinely requires it (e.g. writing/modifying code). Do NOT explore the project for GUI-only tasks like "open Postman" or "click a button".
- For any task involving a desktop app (Postman, Chrome, IntelliJ, Slack, etc.):
    1. If the task is ambiguous (e.g. "make a GET request" without a URL), ask the user for the missing details BEFORE doing anything — do not infer URLs or endpoints from the workspace code.
    2. Use open_app to launch the app (or focus_app if it's already running)
    3. Use screenshot(focus="AppName") to capture the app in focus
    4. Use vision_find to locate UI elements
    5. To type into a field: use click_and_type(x, y, text, focus="AppName") — this clicks AND types atomically so focus is never lost between steps. Never use mouse_click followed by keyboard_type separately.
    6. Use keyboard_hotkey for shortcuts (e.g. Enter to send)
- When an error occurs, analyze it and fix it automatically before reporting to the user
- Never run destructive commands (rm -rf, drop database, etc.) without explicit user confirmation
- Work within the provided workspace directory

GUI tools: open_app, focus_app, screenshot, mouse_click, keyboard_type, keyboard_hotkey, vision_find
Code tools: run_shell, write_file, read_file, list_files, search_repo,
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