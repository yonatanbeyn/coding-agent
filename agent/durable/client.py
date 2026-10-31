"""Terminal client for durable runs: start or attach, stream progress, answer approvals.

The client holds no agent state. It walks the workflow tree (main agent →
sub-agents) with the `status` query, prints new events, prompts for pending
approvals and sends `decide` signals. Ctrl+C only detaches: the agents keep
running on the worker and you can re-attach later with --attach.
"""

import asyncio
import uuid

from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule
from temporalio.client import Client, WorkflowHandle
from temporalio.service import RPCError

from config import Config
from agent.durable.types import AgentInput, ApprovalDecision, AgentStatus
from agent.durable.workflow import AgentWorkflow
from agent.permissions import Decision, PermissionManager, PermissionTier

console = Console()

POLL_SECONDS = 1.0


class DurableRunWatcher:
    """Mirrors one workflow tree in the terminal."""

    def __init__(self, client: Client, root_id: str, permissions: PermissionManager):
        self.client = client
        self.root_id = root_id
        self.permissions = permissions
        self._seen_events: dict[str, int] = {}
        self._answered: set[tuple[str, str]] = set()
        self._finished: set[str] = set()   # children whose final events were already printed

    async def poll_once(self) -> None:
        await self._poll(self.root_id, depth=0)

    async def _poll(self, workflow_id: str, depth: int) -> None:
        handle = self.client.get_workflow_handle(workflow_id)
        try:
            status: AgentStatus = await handle.query(AgentWorkflow.status, self._seen_events.get(workflow_id, 0))
        except RPCError:
            return  # child not started yet or already cleaned up

        indent = "  " * depth
        for event in status.events:
            console.print(f"{indent}[magenta]{status.label}[/magenta] [dim]·[/dim] {event}")
        self._seen_events[workflow_id] = status.total_events

        for pending in status.pending:
            key = (workflow_id, pending.call_id)
            if key in self._answered:
                continue
            console.print(f"{indent}[yellow]Approval needed by[/yellow] [bold]{status.label}[/bold]")
            decision = await asyncio.to_thread(
                self.permissions.check, pending.tool, pending.arguments, PermissionTier.ASK
            )
            allow = decision in (Decision.ALLOWED, Decision.ALLOWED_ALWAYS)
            await handle.signal(AgentWorkflow.decide, ApprovalDecision(call_id=pending.call_id, allow=allow))
            self._answered.add(key)

        for child in status.children:
            if child.workflow_id in self._finished:
                continue
            await self._poll(child.workflow_id, depth + 1)
            if child.done:
                self._finished.add(child.workflow_id)

    async def wait(self, handle: WorkflowHandle) -> None:
        result_task = asyncio.ensure_future(handle.result())
        while not result_task.done():
            await self.poll_once()
            await asyncio.wait({result_task}, timeout=POLL_SECONDS)
        await self.poll_once()  # flush the last events
        result = result_task.result()
        console.print()
        console.print(Rule("[bold cyan]Result[/bold cyan]"))
        if result.final_text:
            console.print(Markdown(result.final_text))
        console.print(
            f"\n[dim]Done in {result.steps} step(s) · "
            f"{result.input_tokens}↑ {result.output_tokens}↓ tokens (including sub-agents)[/dim]"
        )


async def run_durable(
    config: Config,
    prompt: str | None,
    agent_skill: str | None = None,
    enable_aws: bool = True,
    auto_allow_all: bool = False,
    attach_id: str | None = None,
) -> None:
    client = await Client.connect(config.temporal_address, namespace=config.temporal_namespace)

    if attach_id:
        handle = client.get_workflow_handle(attach_id)
        console.print(f"[cyan]Attached to[/cyan] {attach_id}")
    else:
        workflow_id = f"coding-agent-{uuid.uuid4().hex[:8]}"
        handle = await client.start_workflow(
            AgentWorkflow.run,
            AgentInput(
                workspace=config.workspace,
                provider=config.provider,
                model=config.model,
                base_url=config.base_url,
                max_iterations=config.max_iterations,
                max_tokens=config.max_tokens,
                prompt=prompt or "",
                enable_aws=enable_aws,
                auto_allow_all=auto_allow_all,
                agent_skill=agent_skill,
            ),
            id=workflow_id,
            task_queue=config.temporal_task_queue,
        )
        console.print(Rule(f"[bold cyan]Durable run[/bold cyan] · {workflow_id}"))
        console.print(
            f"[dim]Task queue {config.temporal_task_queue} · Ctrl+C detaches (the agents keep running) · "
            f"re-attach with: python main.py --attach {workflow_id}[/dim]\n"
        )

    watcher = DurableRunWatcher(client, handle.id, PermissionManager(auto_allow_all=auto_allow_all))
    try:
        await watcher.wait(handle)
    except asyncio.CancelledError:
        _print_detached(handle.id)


def _print_detached(workflow_id: str) -> None:
    console.print(
        f"\n[yellow]Detached.[/yellow] The run continues on the worker.\n"
        f"  Re-attach:  python main.py --attach {workflow_id}\n"
        f"  Inspect:    Temporal UI → workflow {workflow_id}"
    )
