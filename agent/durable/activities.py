"""Activities: every non-deterministic step of an agent (discovery, LLM calls, tools).

Temporal records each activity's result in the workflow history, so after a
crash or restart a workflow replays those results instead of calling the LLM
or re-running a tool again. Activities are synchronous and run in the worker's
thread pool, which is what lets parallel sub-agents work at the same time.
"""

import json
from dataclasses import replace

from temporalio import activity
from temporalio.exceptions import ApplicationError

from config import Config
from agent.capabilities import find_agent_skill, meta_tool_defs, resolve_setup, skill_activation_result
from agent.context import build_context
from agent.durable.types import (
    AgentSetupInfo, LLMRequest, LLMResult, SetupRequest, SkillInfo, ToolOutcome, ToolRequest, ToolScope,
)
from agent.tools.registry import ToolRegistry


def _registry(scope: ToolScope) -> ToolRegistry:
    registry = ToolRegistry(scope.workspace, enable_aws=scope.enable_aws, allowed=scope.allowed_tools)
    registry.unlock(scope.unlocked)
    return registry


@activity.defn
def load_agent_setup(req: SetupRequest) -> AgentSetupInfo:
    """Read the agent skill, skills and delegation targets from disk."""
    base = Config(
        provider=req.provider,
        model=req.model,
        base_url=req.base_url,
        workspace=req.workspace,
        max_iterations=req.max_iterations,
    )
    try:
        agent_skill = find_agent_skill(req.workspace, req.agent_skill) if req.agent_skill else None
    except ValueError as e:
        raise ApplicationError(str(e), non_retryable=True)

    setup = resolve_setup(base, agent_skill, req.depth, tuple(req.callers))
    return AgentSetupInfo(
        label=agent_skill.name if agent_skill else "main",
        model=setup.config.model,
        max_iterations=setup.config.max_iterations,
        system_prompt=setup.system_prompt,
        allowed_tools=setup.allowed_tools,
        skills={
            name: SkillInfo(scope=s.scope, allowed_tools=s.allowed_tools, activation=skill_activation_result(s))
            for name, s in setup.skills.items()
        },
        agent_skills={name: a.scope for name, a in setup.agent_skills.items()},
        workspace_context=build_context(req.workspace),
    )


@activity.defn
def llm_complete(req: LLMRequest) -> LLMResult:
    """One model call. Retried by Temporal on failure (rate limits, timeouts, 5xx)."""
    # Imported here so the workflow sandbox never loads provider SDKs.
    from agent.loop import _build_messages_for_provider, _make_client

    # Credentials come from the worker's environment, never from workflow history.
    env = Config.from_env()
    config = replace(env, provider=req.provider, model=req.model, base_url=req.base_url or env.base_url)
    client = _make_client(config)

    tools = _registry(req.tools).all() + meta_tool_defs(req.has_skills, req.can_delegate)
    response = client.complete(
        messages=_build_messages_for_provider(req.history, req.provider),
        tools=tools,
        system=req.system,
        max_tokens=req.max_tokens,
    )
    return LLMResult(
        content=response.content or "",
        tool_calls=[{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls],
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )


@activity.defn
def run_tool(req: ToolRequest) -> ToolOutcome:
    """Execute one regular tool. Never retried automatically: tools have side effects."""
    content = _registry(req.tools).execute(req.name, req.arguments)
    try:
        is_error = "error" in json.loads(content)
    except (ValueError, TypeError):
        is_error = False
    return ToolOutcome(content=content, is_error=is_error)


ALL_ACTIVITIES = [load_agent_setup, llm_complete, run_tool]
