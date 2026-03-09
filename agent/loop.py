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
from agent.permissions import Decision, PermissionManager
from agent.session import save_workspace

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
    def __init__(self, config: Config, enable_aws: bool = True, auto_allow_all: bool = False):
        self.config = config
        self.client = _make_client(config)
        self.registry = ToolRegistry(config.workspace, enable_aws=enable_aws)
        self.permissions = PermissionManager(auto_allow_all=auto_allow_all)
        self.history: list[dict] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    # ──────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────

    def run(self, user_prompt: str) -> str:
        """Run the agent on a single prompt. Returns the final assistant message."""
        context = build_context(self.config.workspace)
        enriched = f"{context}\n\n---\n\nTask: {user_prompt}"

        self.history.append({"role": "user", "content": enriched})
        console.print(Rule(f"[bold cyan]Agent[/bold cyan] · {self.config.provider}/{self.config.model}"))
        console.print(f"[dim]Workspace:[/dim] {self.config.workspace}")
        console.print()

        return self._loop()

    def interactive(self) -> None:
        """Start an interactive REPL session."""
        save_workspace(self.config.workspace)
        context = build_context(self.config.workspace)

        console.print(Panel.fit(
            f"[bold cyan]Coding Agent[/bold cyan]\n"
            f"Provider: [green]{self.config.provider}[/green]  "
            f"Model: [green]{self.config.model}[/green]\n"
            f"Workspace: [dim]{self.config.workspace}[/dim]\n"
            f"Tools: [yellow]{len(self.registry.all())}[/yellow] available\n\n"
            f"[dim]Ctrl+C to interrupt · Ctrl+C twice to exit · "
            f"[bold]/tools[/bold] · [bold]/permissions[/bold] · [bold]/help[/bold][/dim]",
            title="[bold]Welcome[/bold]",
            border_style="cyan",
        ))
        console.print()

        # Inject context once at session start
        context_msg = f"Session context:\n{context}"
        self.history.append({"role": "user", "content": context_msg})
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
                break
            except KeyboardInterrupt:
                now = time.time()
                if now - _last_interrupt < 2.0:
                    console.print("\n[dim]Goodbye.[/dim]")
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
        tools = self.registry.all()
        final_text = ""

        for iteration in range(self.config.max_iterations):
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
                        system=self.config.system_prompt,
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
                system=self.config.system_prompt,
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
            system=self.config.system_prompt,
            max_tokens=self.config.max_tokens,
        )

    def _execute_tool_gated(self, tc: ToolCall) -> dict:
        """Check permissions, then execute the tool (or return a denial to the LLM)."""
        decision = self.permissions.check(tc.name, tc.arguments)

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
            return False

        if c == "/clear":
            self.history.clear()
            self.total_input_tokens = 0
            self.total_output_tokens = 0
            console.clear()
            console.print("[green]Session cleared.[/green]")
            return True

        if c == "/tools":
            console.print(Rule("[bold]Available Tools[/bold]"))
            for tool in sorted(self.registry.all(), key=lambda t: t.name):
                console.print(f"  [cyan]{tool.name:<30}[/cyan] {tool.description[:60]}")
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
            self.config.workspace = new_path
            self.registry = ToolRegistry(new_path, enable_aws=self.config.enable_aws)
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