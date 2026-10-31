"""Temporal worker: hosts AgentWorkflow and runs its activities.

Run it on the machine that has the workspace (and, for GUI skills, the
desktop). Start several workers on the same task queue to spread work; if one
dies, Temporal moves its workflows to another and they continue from history.

    python main.py --worker
"""

import os
from concurrent.futures import ThreadPoolExecutor

from rich.console import Console
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from config import Config
from agent.durable.activities import ALL_ACTIVITIES
from agent.durable.workflow import AgentWorkflow

console = Console()


# The workflow only uses pure helpers from these packages, but importing `agent`
# pulls in rich, yaml and the provider SDKs, which the sandbox would re-import
# and reject. Passing them through loads them once, outside the sandbox.
_PASSTHROUGH = ("agent", "config", "rich", "yaml", "anthropic", "openai", "boto3", "pyautogui")


def build_worker(
    client: Client,
    task_queue: str,
    max_concurrent_activities: int = 10,
    activities: list | None = None,
) -> Worker:
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[AgentWorkflow],
        activities=activities or ALL_ACTIVITIES,
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules(*_PASSTHROUGH)
        ),
        # Activities are synchronous (LLM SDKs, subprocess); the pool size is how many
        # LLM calls / tools can run at once across all parallel sub-agents.
        activity_executor=ThreadPoolExecutor(max_workers=max_concurrent_activities),
        max_concurrent_activities=max_concurrent_activities,
    )


async def run_worker(config: Config) -> None:
    client = await Client.connect(config.temporal_address, namespace=config.temporal_namespace)
    max_activities = int(os.getenv("TEMPORAL_MAX_CONCURRENT_ACTIVITIES", "10"))
    worker = build_worker(client, config.temporal_task_queue, max_activities)
    console.print(
        f"[bold cyan]Coding agent worker[/bold cyan] · {config.temporal_address} · "
        f"namespace [green]{config.temporal_namespace}[/green] · "
        f"task queue [green]{config.temporal_task_queue}[/green] · "
        f"{max_activities} concurrent activities\n[dim]Ctrl+C to stop.[/dim]"
    )
    await worker.run()
