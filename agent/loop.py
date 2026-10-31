"""Core agent loop.

Implements the LLM ↔ Tool ↔ LLM cycle that powers the coding agent.
Supports both Anthropic and OpenAI-compatible providers.
"""

import json
import sys
import time
from typing import Callable

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from config import Config
from agent.context import build_context
from agent.llm.base import LLMResponse, ToolCall
from agent.tools.registry import ToolRegistry
from agent.permissions import Decision, PermissionManager, PermissionTier
from agent.session import save_workspace
from agent.skills import Skill
from agent.agent_skills import AgentSkill
from agent.capabilities import (
    MAX_DEPTH, MAX_PARALLEL, compose_system_prompt, find_agent_skill, meta_tool_defs,
    resolve_setup, skill_activation_result, subagent_first_message,
)

console = Console()


def _make_client(config: Config):
    if config.provider == "anthropic":
        from agent.llm.anthropic_client import AnthropicClient
        return AnthropicClient(api_key=config.api_key, model=config.model)
    if config.provider in ("openai", "ollama"):
        from agent.llm.openai_client import OpenAIClient
        base_url = config.base_url
        if config.provider == "ollama" and not base_url:
            base_url = "http://localhost:11434/v1"
        return OpenAIClient(api_key=config.api_key, model=config.model, base_url=base_url)
    raise ValueError(f"Unknown provider: {config.provider!r}. Choose: anthropic, openai, ollama")


def _build_messages_for_provider(history: list[dict], provider: str) -> list[dict]:
    if provider == "anthropic":
        from agent.llm.anthropic_client import build_anthropic_messages
        return build_anthropic_messages(history)
    from agent.llm.openai_client import build_openai_messages
    return build_openai_messages(history)


class AgentLoop:
    """Runs one agent in this process.

    With `agent_skill=None` this is the default coding agent. With an AgentSkill
    the loop *becomes* that agent: its body is the system prompt, its `tools:`
    is the tool allowlist, its `skills:` limits which skills it can activate,
    and its `model:` overrides the model. Sub-agents (depth > 0) are created
    the same way by `delegate_to_agent`. For durable, parallel teams see
    agent/durable/ (the same agents running as Temporal workflows).
    """

    MAX_DEPTH = MAX_DEPTH

    def __init__(
        self,
        config: Config,
        enable_aws: bool = True,
        auto_allow_all: bool = False,
        agent_skill: AgentSkill | str | None = None,
        permissions: PermissionManager | None = None,
        depth: int = 0,
        callers: tuple[str, ...] = (),
    ):
        self.enable_aws = enable_aws
        self.depth = depth
        self._callers = callers
        self.permissions = permissions or PermissionManager(auto_allow_all=auto_allow_all)
        self.history: list[dict] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        if isinstance(agent_skill, str):
            agent_skill = find_agent_skill(config.workspace, agent_skill)
        self.agent_skill: AgentSkill | None = agent_skill
        self._base_config = config
        self._setup_capabilities()

    # ──────────────────────────────────────────────────────────────
    # Skills & agent skills
    # ──────────────────────────────────────────────────────────────

    def _setup_capabilities(self) -> None:
        """(Re)build tools, skills and agent skills for the current workspace."""
        setup = resolve_setup(self._base_config, self.agent_skill, self.depth, self._callers)
        self.config = setup.config
        self.client = _make_client(self.config)
        self.registry = ToolRegistry(self.config.workspace, enable_aws=self.enable_aws, allowed=setup.allowed_tools)
        self.skills: dict[str, Skill] = setup.skills
        self.agent_skills: dict[str, AgentSkill] = setup.agent_skills
        self.capability_problems = setup.problems
        self.active_skills: list[str] = []

        handlers = {
            "activate_skill": self._activate_skill,
            "delegate_to_agent": self._delegate_to_agent,
            "delegate_parallel": self._delegate_parallel,
        }
        for tool in meta_tool_defs(bool(self.skills), bool(self.agent_skills)):
            tool.fn = handlers[tool.name]
            self.registry.register(tool, meta=True)

    @property
    def system_prompt(self) -> str:
        return compose_system_prompt(self.config.system_prompt, self.skills, self.agent_skills)

    def _activate_skill(self, name: str) -> dict:
        skill = self.skills.get(name)
        if not skill:
            return {"error": f"Unknown skill {name!r}. Available: {', '.join(sorted(self.skills)) or 'none'}"}
        unlocked = self.registry.unlock(skill.allowed_tools)
        if name not in self.active_skills:
            self.active_skills.append(name)
        console.print(f"[magenta]◆ Skill activated:[/magenta] [bold]{name}[/bold] [dim]({skill.scope})[/dim]")
        result = skill_activation_result(skill)
        if unlocked:
            result["tools_unlocked"] = unlocked
        missing = [t for t in skill.allowed_tools if not self.registry.is_visible(t)]
        if missing:
            result["tools_unavailable"] = missing
        return result

    def _delegate_to_agent(self, agent: str, task: str) -> dict:
        target = self.agent_skills.get(agent)
        if not target:
            return {"error": f"Unknown agent skill {agent!r}. Available: {', '.join(sorted(self.agent_skills)) or 'none'}"}

        sub = AgentLoop(
            self._base_config,
            enable_aws=self.enable_aws,
            agent_skill=target,
            permissions=self.permissions,   # same user, same session approvals
            depth=self.depth + 1,
            callers=self._callers + ((self.agent_skill.name,) if self.agent_skill else ()),
        )
        sub.history = [{
            "role": "user",
            "content": subagent_first_message(build_context(self.config.workspace), task),
        }]

        console.print(Rule(f"[bold magenta]→ agent skill: {target.name}[/bold magenta] · {sub.config.model}"))
        try:
            answer = sub._loop()
        finally:
            self.total_input_tokens += sub.total_input_tokens
            self.total_output_tokens += sub.total_output_tokens
            console.print(Rule(f"[bold magenta]← back from {target.name}[/bold magenta]"))

        return {"agent": target.name, "result": answer or "(the sub-agent returned no text)"}

    def _delegate_parallel(self, tasks: list[dict]) -> dict:
        """In-process runtime: same contract as the durable one, but runs the tasks in sequence."""
        if not tasks or len(tasks) > MAX_PARALLEL:
            return {"error": f"Pass between 1 and {MAX_PARALLEL} tasks."}
        console.print(
            f"[dim]delegate_parallel: running {len(tasks)} task(s) one after another "
            f"(use --durable for real parallelism)[/dim]"
        )
        return {"results": [self._delegate_to_agent(t.get("agent", ""), t.get("task", "")) for t in tasks]}

    # ──────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────

    def run(self, user_prompt: str) -> str:
        """Run the agent on a single prompt. Returns the final assistant message."""
        context = build_context(self.config.workspace)
        # Provide workspace context as a separate system-style message so the
        # agent has it available without feeling compelled to re-explore files.
        self.history.append({
            "role": "user",
            "content": (
                f"Workspace context (for reference only — do NOT read files, infer endpoints, "
                f"or use this project's details unless the user's task explicitly involves modifying or reading code):\n{context}"
            ),
        })
        self.history.append({
            "role": "assistant",
            "content": "Got it. Ready.",
        })
        self.history.append({"role": "user", "content": user_prompt})

        console.print(Rule(f"[bold cyan]{self._agent_label()}[/bold cyan] · {self.config.provider}/{self.config.model}"))
        console.print(f"[dim]Workspace:[/dim] {self.config.workspace}")
        console.print()

        return self._loop()

    def interactive(self, skip_context_inject: bool = False) -> None:
        """Start an interactive REPL session.

        Args:
            skip_context_inject: If True, skip the initial context injection
                (used when continuing after a one-shot run that already has history).
        """
        save_workspace(self.config.workspace)

        console.print(Panel.fit(
            f"[bold cyan]{self._agent_label()}[/bold cyan]\n"
            f"Provider: [green]{self.config.provider}[/green]  "
            f"Model: [green]{self.config.model}[/green]\n"
            f"Workspace: [dim]{self.config.workspace}[/dim]\n"
            f"Tools: [yellow]{len(self.registry.all())}[/yellow] available · "
            f"Skills: [yellow]{len(self.skills)}[/yellow] · "
            f"Agent skills: [yellow]{len(self.agent_skills)}[/yellow]\n\n"
            f"[dim]Ctrl+C to interrupt · Ctrl+C twice to exit · "
            f"[bold]/skills[/bold] · [bold]/agents[/bold] · [bold]/tools[/bold] · [bold]/help[/bold][/dim]",
            title="[bold]Welcome[/bold]",
            border_style="cyan",
        ))
        console.print()

        if not skip_context_inject:
            context = build_context(self.config.workspace)
            self.history.append({"role": "user", "content": f"Session context:\n{context}"})
            self.history.append({
                "role": "assistant",
                "content": "Understood. I have your workspace context. What would you like to build?",
            })

        _last_interrupt = 0.0

        while True:
            try:
                user_input = console.input("[bold green]You>[/bold green] ").strip()
                _last_interrupt = 0.0  # reset on successful input
            except EOFError:
                console.print("\n[dim]Goodbye.[/dim]")
                self.history.clear()
                break
            except KeyboardInterrupt:
                now = time.time()
                if now - _last_interrupt < 2.0:
                    console.print("\n[dim]Goodbye.[/dim]")
                    self.history.clear()
                    break
                _last_interrupt = now
                console.print("\n[dim]Press Ctrl+C again to exit.[/dim]")
                continue

            if not user_input:
                continue

            # Slash commands
            if user_input.startswith("/"):
                if self._handle_slash(user_input):
                    continue
                break

            self.history.append({"role": "user", "content": user_input})
            console.print()
            try:
                self._loop()
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted.[/yellow] Returning to prompt…")
                # Remove the unanswered user message so history stays clean
                if self.history and self.history[-1]["role"] == "user":
                    self.history.pop()
            console.print()

    # ──────────────────────────────────────────────────────────────
    # Internal loop
    # ──────────────────────────────────────────────────────────────

    def _loop(self) -> str:
        """Run the agent loop until the LLM stops calling tools."""
        final_text = ""

        for iteration in range(self.config.max_iterations):
            # Re-read every turn: activating a skill can unlock more tools.
            tools = self.registry.all()
            messages = _build_messages_for_provider(self.history, self.config.provider)

            # ── Call the LLM ──
            console.print("[dim]Thinking…[/dim]", end="\r")
            t0 = time.time()

            try:
                if self.config.stream and hasattr(self.client, "complete_after_stream"):
                    response = self._stream_response(messages, tools)
                else:
                    response = self.client.complete(
                        messages=messages,
                        tools=tools,
                        system=self.system_prompt,
                        max_tokens=self.config.max_tokens,
                    )
                    if response.content:
                        console.print(Markdown(response.content))
            except KeyboardInterrupt:
                raise  # let interactive() catch it
            except Exception as e:
                console.print(f"[red]LLM error:[/red] {e}")
                break

            elapsed = time.time() - t0
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            if response.content:
                final_text = response.content

            # ── Record assistant message ──
            assistant_msg: dict = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ],
            }
            self.history.append(assistant_msg)

            # ── No tool calls → done ──
            if not response.tool_calls:
                console.print(
                    f"\n[dim]Done in {iteration+1} step(s) · "
                    f"{self.total_input_tokens}↑ {self.total_output_tokens}↓ tokens · "
                    f"{elapsed:.1f}s[/dim]"
                )
                break

            # ── Execute tools ──
            tool_results = []
            for tc in response.tool_calls:
                tool_results.append(self._execute_tool_gated(tc))

            self.history.append({
                "role": "tool",
                "tool_results": tool_results,
            })

        else:
            console.print(f"[yellow]Reached max iterations ({self.config.max_iterations})[/yellow]")

        return final_text

    def _stream_response(self, messages, tools) -> LLMResponse:
        """Stream text output then return the complete response."""
        from agent.llm.anthropic_client import AnthropicClient
        from agent.llm.openai_client import OpenAIClient

        if isinstance(self.client, AnthropicClient):
            # Use the special streaming method
            with self.client.client.messages.stream(
                model=self.client.model,
                max_tokens=self.config.max_tokens,
                system=self.system_prompt,
                messages=messages,
                tools=[{"name": t.name, "description": t.description, "input_schema": t.parameters}
                       for t in tools] if tools else [],
            ) as stream:
                text_chunks = []
                for text in stream.text_stream:
                    console.print(text, end="", markup=False)
                    text_chunks.append(text)
                console.print()  # newline after stream
                final = stream.get_final_message()

            from agent.llm.base import LLMResponse, ToolCall
            tool_calls = []
            for block in final.content:
                if block.type == "tool_use":
                    tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

            return LLMResponse(
                content="".join(text_chunks),
                tool_calls=tool_calls,
                stop_reason=final.stop_reason or "end_turn",
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
            )

        # Fallback: non-streaming
        return self.client.complete(
            messages=messages,
            tools=tools,
            system=self.system_prompt,
            max_tokens=self.config.max_tokens,
        )

    def _execute_tool_gated(self, tc: ToolCall) -> dict:
        """Check permissions, then execute the tool (or return a denial to the LLM)."""
        decision = self.permissions.check(tc.name, tc.arguments, tier=self._tier_override(tc))

        if decision in (Decision.DENIED, Decision.DENIED_ALWAYS):
            denial = json.dumps({
                "error": "User denied this tool call.",
                "tool": tc.name,
                "hint": "Do not retry this tool unless the user explicitly asks.",
            })
            return {
                "tool_call_id": tc.id,
                "name": tc.name,
                "content": denial,
                "is_error": True,
            }

        return self._execute_tool(tc)

    def _tier_override(self, tc: ToolCall) -> PermissionTier | None:
        """Skills and agent skills from the workspace may come from an untrusted repo: ask first."""
        if tc.name == "activate_skill":
            item = self.skills.get(tc.arguments.get("name", ""))
        elif tc.name == "delegate_to_agent":
            item = self.agent_skills.get(tc.arguments.get("agent", ""))
        elif tc.name == "delegate_parallel":
            names = [t.get("agent", "") for t in tc.arguments.get("tasks", []) if isinstance(t, dict)]
            project = any(self.agent_skills.get(n) and self.agent_skills[n].scope == "project" for n in names)
            return PermissionTier.ASK if project else None
        else:
            return None
        return PermissionTier.ASK if item and item.scope == "project" else None

    def _agent_label(self) -> str:
        return f"Agent skill: {self.agent_skill.name}" if self.agent_skill else "Coding Agent"

    def _execute_tool(self, tc: ToolCall) -> dict:
        """Execute a single tool call and pretty-print the result."""
        result_str = self.registry.execute(tc.name, tc.arguments)
        is_error = False

        try:
            result_obj = json.loads(result_str)
            is_error = "error" in result_obj
            preview = json.dumps(result_obj, indent=2)[:500]
            if is_error:
                console.print(f"  [red]Error:[/red] {result_obj.get('error')}")
            else:
                console.print(Syntax(preview, "json", theme="monokai", line_numbers=False))
        except Exception:
            console.print(f"  [dim]{result_str[:200]}[/dim]")

        return {
            "tool_call_id": tc.id,
            "name": tc.name,
            "content": result_str,
            "is_error": is_error,
        }

    # ──────────────────────────────────────────────────────────────
    # Slash commands
    # ──────────────────────────────────────────────────────────────

    def _handle_slash(self, cmd: str) -> bool:
        """Handle REPL slash commands. Returns True to continue, False to exit."""
        parts = cmd.split()
        c = parts[0].lower()

        if c in ("/exit", "/quit", "/q"):
            console.print("[dim]Goodbye.[/dim]")
            self.history.clear()
            return False

        if c == "/clear":
            self.history.clear()
            self.total_input_tokens = 0
            self.total_output_tokens = 0
            self.registry.reset_unlocked()
            self.active_skills.clear()
            console.clear()
            console.print("[green]Session cleared.[/green]")
            return True

        if c == "/tools":
            console.print(Rule("[bold]Available Tools[/bold]"))
            for tool, visible in sorted(self.registry.all_registered(), key=lambda tv: tv[0].name):
                if visible:
                    console.print(f"  [cyan]{tool.name:<30}[/cyan] {tool.description[:60]}")
                else:
                    console.print(f"  [dim]{tool.name:<30} (hidden — unlocked by a skill or not allowed)[/dim]")
            return True

        if c == "/skills":
            if len(parts) > 1 and parts[1] == "reload":
                self._setup_capabilities()
                console.print(f"[green]Reloaded:[/green] {len(self.skills)} skills, {len(self.agent_skills)} agent skills")
                return True
            console.print(Rule("[bold]Skills[/bold] [dim]— know-how loaded into the current agent[/dim]"))
            if not self.skills:
                console.print("  [dim]No skills found.[/dim]")
            for s in self.skills.values():
                mark = "[magenta]●[/magenta]" if s.name in self.active_skills else " "
                console.print(f" {mark} [cyan]{s.name:<24}[/cyan] [dim]{s.scope:<8}[/dim] {s.description[:70]}")
            self._print_problems()
            return True

        if c == "/agents":
            console.print(Rule("[bold]Agent skills[/bold] [dim]— agents this agent can delegate to[/dim]"))
            if self.agent_skill:
                console.print(f"  Running as: [bold]{self.agent_skill.name}[/bold] [dim]({self.agent_skill.path})[/dim]")
            if not self.agent_skills:
                console.print("  [dim]No agent skills available for delegation.[/dim]")
            for a in self.agent_skills.values():
                tools = ", ".join(a.tools) if a.tools is not None else "all"
                console.print(f"  [cyan]{a.name:<24}[/cyan] [dim]{a.scope:<8}[/dim] {a.description[:70]}")
                console.print(f"  {'':<24} [dim]tools: {tools[:70]} · model: {a.model or 'inherit'}[/dim]")
            self._print_problems()
            return True

        if c == "/tokens":
            console.print(
                f"Input tokens: [yellow]{self.total_input_tokens}[/yellow]  "
                f"Output tokens: [yellow]{self.total_output_tokens}[/yellow]"
            )
            return True

        if c == "/history":
            console.print(Rule("[bold]Message History[/bold]"))
            for i, msg in enumerate(self.history):
                role = msg["role"]
                content = str(msg.get("content", ""))[:80]
                console.print(f"  {i:2}. [{role}] {content}")
            return True

        if c == "/workspace":
            console.print(f"Workspace: [cyan]{self.config.workspace}[/cyan]")
            return True

        if c == "/cd":
            if len(parts) < 2:
                console.print("[dim]Usage: /cd <path>[/dim]")
                return True
            import os as _os
            new_path = _os.path.abspath(parts[1])
            if not _os.path.isdir(new_path):
                console.print(f"[red]Not a directory:[/red] {new_path}")
                return True
            self._base_config.workspace = new_path
            self._setup_capabilities()
            save_workspace(new_path)
            context = build_context(new_path)
            self.history.append({"role": "user", "content": f"I switched workspace to:\n{context}"})
            self.history.append({"role": "assistant", "content": f"Switched workspace to `{new_path}`."})
            console.print(f"[green]Workspace → {new_path}[/green]")
            return True

        if c in ("/help", "/?"):
            console.print(Rule("[bold]Commands[/bold]"))
            cmds = [
                ("/cd <path>",      "Switch workspace directory"),
                ("/workspace",      "Show current workspace"),
                ("/tools",          "List all available tools"),
                ("/skills [reload]", "List skills (know-how loaded into this agent)"),
                ("/agents",         "List agent skills (sub-agents you can delegate to)"),
                ("/permissions",    "Show session allow/deny list"),
                ("/tokens",         "Show token usage"),
                ("/history",        "Show conversation history"),
                ("/clear",          "Reset conversation"),
                ("/exit",           "Quit (or Ctrl+C twice)"),
            ]
            for name, desc in cmds:
                console.print(f"  [cyan]{name:<20}[/cyan] {desc}")
            return True

        if c == "/permissions":
            console.print(Rule("[bold]Session Permissions[/bold]"))
            allowed = self.permissions.always_allowed
            denied = self.permissions.always_denied
            if allowed:
                console.print("  [green]Always allowed:[/green]")
                for name in sorted(allowed):
                    console.print(f"    [cyan]{name}[/cyan]")
            if denied:
                console.print("  [red]Always denied:[/red]")
                for name in sorted(denied):
                    console.print(f"    [cyan]{name}[/cyan]")
            if not allowed and not denied:
                console.print("  [dim]No session overrides yet.[/dim]")
            return True

        console.print(f"[yellow]Unknown command:[/yellow] {cmd}  [dim](type /help for list)[/dim]")
        return True

    def _print_problems(self) -> None:
        for problem in self.capability_problems:
            console.print(f"  [yellow]⚠ skipped:[/yellow] [dim]{problem}[/dim]")
