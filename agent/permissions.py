"""Permission system — ask user before running tools, like Claude Code does."""

import json
from enum import Enum

from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text

console = Console()


class PermissionTier(Enum):
    AUTO_ALLOW = "auto_allow"  # safe read-only tools — run without asking
    ASK        = "ask"         # write / execute tools — ask each time
    DENY       = "deny"        # never allow in this session


class Decision(Enum):
    ALLOWED        = "allowed"
    ALLOWED_ALWAYS = "allowed_always"  # user chose "always" — skip future prompts
    DENIED         = "denied"
    DENIED_ALWAYS  = "denied_always"


# Default tier for every tool
_DEFAULT_TIERS: dict[str, PermissionTier] = {
    # ── Auto-allow (read-only / non-destructive) ──────────────────
    "read_file":            PermissionTier.AUTO_ALLOW,
    "list_files":           PermissionTier.AUTO_ALLOW,
    "search_repo":          PermissionTier.AUTO_ALLOW,
    "check_command_exists": PermissionTier.AUTO_ALLOW,
    "git_status":           PermissionTier.AUTO_ALLOW,
    "git_diff":             PermissionTier.AUTO_ALLOW,
    "git_log":              PermissionTier.AUTO_ALLOW,

    # ── Ask (write / execute / install / network) ─────────────────
    "write_file":              PermissionTier.ASK,
    "run_shell":               PermissionTier.ASK,
    "run_tests":               PermissionTier.ASK,
    "git_add":                 PermissionTier.ASK,
    "git_commit":              PermissionTier.ASK,
    "git_clone":               PermissionTier.ASK,
    "install_maven":           PermissionTier.ASK,
    "install_node":            PermissionTier.ASK,
    "install_python_package":  PermissionTier.ASK,
    "install_dependency":      PermissionTier.ASK,
    "list_s3_buckets":         PermissionTier.ASK,
    "get_aws_billing":         PermissionTier.ASK,
    "list_ec2_instances":      PermissionTier.ASK,
    "get_s3_bucket_size":      PermissionTier.ASK,
}


def _format_args(arguments: dict) -> str:
    """Pretty-format tool arguments for display."""
    if not arguments:
        return ""
    try:
        return json.dumps(arguments, indent=2, ensure_ascii=False)
    except Exception:
        return str(arguments)


class PermissionManager:
    """
    Tracks per-session tool permissions.
    Mimics Claude Code's allow/deny prompt before tool execution.
    """

    def __init__(self, auto_allow_all: bool = False):
        self._session_always_allow: set[str] = set()
        self._session_always_deny: set[str] = set()
        self._auto_allow_all = auto_allow_all  # --yes / -y flag

    def check(self, tool_name: str, arguments: dict) -> Decision:
        """
        Check whether a tool call should be allowed.

        Returns a Decision. If ASK, prints a prompt and waits for input.
        """
        # Session overrides take priority
        if tool_name in self._session_always_allow:
            _print_auto(tool_name, arguments, "always allowed")
            return Decision.ALLOWED_ALWAYS

        if tool_name in self._session_always_deny:
            _print_auto(tool_name, arguments, "always denied")
            return Decision.DENIED_ALWAYS

        tier = _DEFAULT_TIERS.get(tool_name, PermissionTier.ASK)

        if tier == PermissionTier.AUTO_ALLOW or self._auto_allow_all:
            _print_auto(tool_name, arguments, "auto")
            return Decision.ALLOWED

        if tier == PermissionTier.DENY:
            console.print(f"[red]✗ Denied (policy):[/red] [cyan]{tool_name}[/cyan]")
            return Decision.DENIED

        # tier == ASK → prompt the user
        return self._prompt(tool_name, arguments)

    def _prompt(self, tool_name: str, arguments: dict) -> Decision:
        """Show the tool call and ask the user y/n/a/d."""
        args_str = _format_args(arguments)

        console.print()
        console.print(Text("┌─ Tool request ", style="bold yellow") + Text("─" * 40, style="dim yellow"))
        console.print(f"  [bold cyan]{tool_name}[/bold cyan]")
        if args_str:
            console.print(Syntax(args_str, "json", theme="monokai", line_numbers=False, indent_guides=False))
        console.print(Text("└" + "─" * 48, style="dim yellow"))
        console.print(
            "  [bold green](y)[/bold green] yes  "
            "[bold green](a)[/bold green] always allow  "
            "[bold red](n)[/bold red] no  "
            "[bold red](d)[/bold red] always deny  "
            "[dim](q) abort[/dim]"
        )

        while True:
            try:
                raw = console.input("  Allow? ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                raw = "n"

            if raw in ("y", "yes", ""):
                console.print("  [green]✓ Allowed[/green]")
                return Decision.ALLOWED

            if raw in ("a", "always"):
                self._session_always_allow.add(tool_name)
                console.print(f"  [green]✓ Always allowed[/green] [dim](for this session)[/dim]")
                return Decision.ALLOWED_ALWAYS

            if raw in ("n", "no"):
                console.print("  [red]✗ Denied[/red]")
                return Decision.DENIED

            if raw in ("d", "deny"):
                self._session_always_deny.add(tool_name)
                console.print(f"  [red]✗ Always denied[/red] [dim](for this session)[/dim]")
                return Decision.DENIED_ALWAYS

            if raw in ("q", "quit", "abort"):
                console.print("  [red]✗ Aborted[/red]")
                return Decision.DENIED

            console.print("  [dim]Please enter y / a / n / d / q[/dim]")

    def allow_tool(self, tool_name: str) -> None:
        """Programmatically always-allow a tool (e.g. from --yes flag)."""
        self._session_always_allow.add(tool_name)

    def deny_tool(self, tool_name: str) -> None:
        """Programmatically always-deny a tool."""
        self._session_always_deny.add(tool_name)

    @property
    def always_allowed(self) -> set[str]:
        return frozenset(self._session_always_allow)

    @property
    def always_denied(self) -> set[str]:
        return frozenset(self._session_always_deny)


def _print_auto(tool_name: str, arguments: dict, reason: str) -> None:
    args_preview = json.dumps(arguments, ensure_ascii=False) if arguments else ""
    if len(args_preview) > 100:
        args_preview = args_preview[:97] + "…"
    console.print(
        f"[dim]⚙ {tool_name}[/dim]"
        + (f" [dim]{args_preview}[/dim]" if args_preview else "")
        + f" [dim italic]({reason})[/dim italic]"
    )