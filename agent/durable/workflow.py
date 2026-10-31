"""AgentWorkflow: one agent as a durable Temporal workflow.

The workflow is the deterministic agent loop: it only decides what happens
next. Every side effect (discovering skills, calling the LLM, running a tool)
is an activity, and every sub-agent is a child workflow. Temporal persists the
result of each step, so a crashed worker or a restarted machine resumes the
agent exactly where it stopped.

    main agent ──────── AgentWorkflow (depth 0)
      └─ feature-lead ── child AgentWorkflow (depth 1)
           ├─ implementer   child AgentWorkflow (depth 2) ┐ delegate_parallel:
           └─ code-reviewer child AgentWorkflow (depth 2) ┘ run at the same time

Approvals: when a tool needs the user's OK, the workflow records a pending
approval (visible through the `status` query) and durably waits for a
`decide` signal from the client, for up to APPROVAL_TIMEOUT.
"""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from agent.capabilities import MAX_PARALLEL, subagent_first_message
    from agent.durable.activities import llm_complete, load_agent_setup, run_tool
    from agent.durable.types import (
        AgentInput, AgentResult, AgentSetupInfo, AgentStatus, ApprovalDecision, ChildInfo, LLMRequest,
        PendingApproval, SetupRequest, ToolRequest, ToolScope,
    )
    from agent.permissions import PermissionTier, default_tier

APPROVAL_TIMEOUT = timedelta(hours=24)

# LLM calls are safe to repeat: retry rate limits, overloads and timeouts with backoff.
LLM_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=6,
)
# Tools have side effects (git commit, file writes, installs): run at most once.
TOOL_RETRY = RetryPolicy(maximum_attempts=1)


def _short(args: dict, limit: int = 80) -> str:
    text = json.dumps(args, ensure_ascii=False) if args else ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


@workflow.defn
class AgentWorkflow:
    def __init__(self) -> None:
        self._label = "agent"
        self._state = "starting"
        self._events: list[str] = []
        self._pending: dict[str, PendingApproval] = {}
        self._decisions: dict[str, bool] = {}
        self._children: list[ChildInfo] = []
        self._child_seq = 0
        self._unlocked: list[str] = []
        self._input_tokens = 0
        self._output_tokens = 0

    # ── Client interface ──────────────────────────────────────────

    @workflow.signal
    def decide(self, decision: ApprovalDecision) -> None:
        """The user's answer to a pending approval."""
        self._decisions[decision.call_id] = decision.allow

    @workflow.query
    def status(self, since: int = 0) -> AgentStatus:
        return AgentStatus(
            label=self._label,
            state=self._state,
            events=self._events[since:],
            total_events=len(self._events),
            pending=list(self._pending.values()),
            children=list(self._children),
        )

    # ── Agent loop ────────────────────────────────────────────────

    @workflow.run
    async def run(self, inp: AgentInput) -> AgentResult:
        self._inp = inp
        self._setup: AgentSetupInfo = await workflow.execute_activity(
            load_agent_setup,
            SetupRequest(
                workspace=inp.workspace, provider=inp.provider, model=inp.model,
                max_iterations=inp.max_iterations, base_url=inp.base_url, enable_aws=inp.enable_aws,
                agent_skill=inp.agent_skill, depth=inp.depth, callers=inp.callers,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        self._label = self._setup.label
        self._state = "running"
        self._log(f"started · model {self._setup.model}")

        if inp.depth == 0:
            history = [
                {"role": "user", "content": f"Workspace context (for reference only):\n{self._setup.workspace_context}"},
                {"role": "assistant", "content": "Got it. Ready."},
                {"role": "user", "content": inp.prompt},
            ]
        else:
            history = [{"role": "user", "content": subagent_first_message(self._setup.workspace_context, inp.prompt)}]

        final_text = ""
        steps = 0
        for steps in range(1, self._setup.max_iterations + 1):
            try:
                response = await workflow.execute_activity(
                    llm_complete,
                    LLMRequest(
                        provider=inp.provider, model=self._setup.model, base_url=inp.base_url,
                        system=self._setup.system_prompt, history=history, max_tokens=inp.max_tokens,
                        tools=self._tool_scope(), has_skills=bool(self._setup.skills),
                        can_delegate=bool(self._setup.agent_skills),
                    ),
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=LLM_RETRY,
                )
            except ActivityError as e:
                # All retries used up (e.g. bad API key, provider down): end like the in-process loop.
                self._log(f"LLM error after retries: {e.cause or e}")
                final_text = final_text or f"LLM error: {e.cause or e}"
                break
            self._input_tokens += response.input_tokens
            self._output_tokens += response.output_tokens
            if response.content:
                final_text = response.content

            history.append({"role": "assistant", "content": response.content, "tool_calls": response.tool_calls})
            if not response.tool_calls:
                break

            results = []
            for call in response.tool_calls:
                content, is_error = await self._handle_tool(call)
                results.append({"tool_call_id": call["id"], "name": call["name"], "content": content, "is_error": is_error})
            history.append({"role": "tool", "tool_results": results})
        else:
            self._log(f"reached max iterations ({self._setup.max_iterations})")

        self._state = "done"
        self._log(f"done in {steps} step(s)")
        return AgentResult(final_text, steps, self._input_tokens, self._output_tokens)

    # ── Tools ─────────────────────────────────────────────────────

    async def _handle_tool(self, call: dict) -> tuple[str, bool]:
        name, args, call_id = call["name"], call.get("arguments") or {}, call["id"]
        self._log(f"→ {name} {_short(args)}")

        if name == "activate_skill":
            return self._result(await self._activate_skill(call_id, args.get("name", "")))
        if name == "delegate_to_agent":
            return self._result(await self._delegate(call_id, [args]))
        if name == "delegate_parallel":
            return self._result(await self._delegate(call_id, args.get("tasks") or [], parallel=True))

        if not await self._approve(call_id, name, args):
            return self._denied(name)
        try:
            outcome = await workflow.execute_activity(
                run_tool,
                ToolRequest(tools=self._tool_scope(), name=name, arguments=args),
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=TOOL_RETRY,
            )
        except ActivityError as e:
            # e.g. the worker died mid-tool: report it to the model instead of re-running blindly.
            return self._result({"error": f"Tool {name} did not complete: {e.cause or e}"})
        if outcome.is_error:
            self._log(f"✗ {name} returned an error")
        return outcome.content, outcome.is_error

    async def _activate_skill(self, call_id: str, name: str) -> dict:
        skill = self._setup.skills.get(name)
        if not skill:
            return {"error": f"Unknown skill {name!r}. Available: {', '.join(sorted(self._setup.skills)) or 'none'}"}
        force_ask = skill.scope == "project"
        if not await self._approve(call_id, "activate_skill", {"name": name}, force_ask=force_ask):
            return json.loads(self._denied("activate_skill")[0])
        new = [t for t in skill.allowed_tools if t not in self._unlocked]
        self._unlocked.extend(new)
        self._log(f"◆ skill activated: {name}")
        result = dict(skill.activation)
        if new:
            result["tools_unlocked"] = new
        return result

    async def _delegate(self, call_id: str, tasks: list, parallel: bool = False) -> dict:
        tasks = [t for t in tasks if isinstance(t, dict)]
        if not tasks or (parallel and len(tasks) > MAX_PARALLEL):
            return {"error": f"Pass between 1 and {MAX_PARALLEL} tasks."}
        unknown = [t.get("agent") for t in tasks if t.get("agent") not in self._setup.agent_skills]
        if unknown:
            return {"error": f"Unknown agent skill(s) {unknown}. Available: {', '.join(sorted(self._setup.agent_skills)) or 'none'}"}

        tool = "delegate_parallel" if parallel else "delegate_to_agent"
        force_ask = any(self._setup.agent_skills[t["agent"]] == "project" for t in tasks)
        if not await self._approve(call_id, tool, {"tasks": tasks} if parallel else tasks[0], force_ask=force_ask):
            return json.loads(self._denied(tool)[0])

        runs = [self._run_child(t["agent"], t.get("task", "")) for t in tasks]
        if not parallel:
            return await runs[0]
        return {"results": list(await asyncio.gather(*runs))}

    async def _run_child(self, agent: str, task: str) -> dict:
        self._child_seq += 1
        child_id = f"{workflow.info().workflow_id}.{self._child_seq}-{agent}"
        info = ChildInfo(workflow_id=child_id, agent=agent)
        self._children.append(info)
        self._log(f"⇢ started sub-agent {agent} ({child_id})")

        me = [self._inp.agent_skill] if self._inp.agent_skill else []
        child_input = replace(
            self._inp,
            agent_skill=agent,
            depth=self._inp.depth + 1,
            callers=self._inp.callers + me,
            prompt=task,
        )
        try:
            result = await workflow.execute_child_workflow(AgentWorkflow.run, child_input, id=child_id)
        except ChildWorkflowError as e:
            self._log(f"⇠ sub-agent {agent} failed")
            return {"agent": agent, "error": f"Sub-agent failed: {e.cause or e}"}
        finally:
            info.done = True
        self._input_tokens += result.input_tokens
        self._output_tokens += result.output_tokens
        self._log(f"⇠ sub-agent {agent} finished")
        return {"agent": agent, "result": result.final_text or "(the sub-agent returned no text)"}

    # ── Approvals ─────────────────────────────────────────────────

    async def _approve(self, call_id: str, tool: str, args: dict, force_ask: bool = False) -> bool:
        if self._inp.auto_allow_all:
            return True
        tier = PermissionTier.ASK if force_ask else default_tier(tool)
        if tier == PermissionTier.AUTO_ALLOW:
            return True
        if tier == PermissionTier.DENY:
            return False

        self._pending[call_id] = PendingApproval(call_id=call_id, tool=tool, arguments=args)
        self._state = "waiting_for_approval"
        self._log(f"? waiting for approval: {tool}")
        try:
            await workflow.wait_condition(lambda: call_id in self._decisions, timeout=APPROVAL_TIMEOUT)
        except asyncio.TimeoutError:
            self._decisions[call_id] = False
            self._log(f"approval for {tool} timed out — denied")
        finally:
            self._pending.pop(call_id, None)
            self._state = "running"
        return self._decisions[call_id]

    # ── Helpers ───────────────────────────────────────────────────

    def _tool_scope(self) -> ToolScope:
        return ToolScope(
            workspace=self._inp.workspace,
            enable_aws=self._inp.enable_aws,
            allowed_tools=self._setup.allowed_tools,
            unlocked=list(self._unlocked),
        )

    def _log(self, text: str) -> None:
        self._events.append(text)

    @staticmethod
    def _result(obj: dict) -> tuple[str, bool]:
        return json.dumps(obj, indent=2, default=str), "error" in obj

    def _denied(self, tool: str) -> tuple[str, bool]:
        self._log(f"✗ {tool} denied by user")
        return self._result({
            "error": "User denied this tool call.",
            "tool": tool,
            "hint": "Do not retry this tool unless the user explicitly asks.",
        })
