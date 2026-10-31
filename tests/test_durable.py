"""End-to-end test of the durable runtime against a real local Temporal dev server.

Uses a scripted fake LLM (no API key needed) with the real workflow, the real
load_agent_setup / run_tool activities and the real client watcher. Checks:
  A. skill activation, an approval answered through the client, and two
     sub-agents started with delegate_parallel actually running at the same time
  B. the worker dies while a run waits for approval; a new worker resumes it
     without repeating the completed LLM call

Run:  python tests/test_durable.py
      (set TEMPORAL_CLI_PATH=/path/to/temporal to use a local CLI binary instead
       of letting the SDK download the dev server)
"""
import asyncio, os, re, sys, tempfile, threading, time, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["HOME"] = tempfile.mkdtemp()

from temporalio import activity
from temporalio.testing import WorkflowEnvironment

from agent.durable.types import AgentInput, ApprovalDecision, LLMRequest, LLMResult
from agent.durable.workflow import AgentWorkflow
from agent.durable.activities import load_agent_setup, run_tool
from agent.durable.client import DurableRunWatcher
from agent.durable import worker as worker_mod
from agent.permissions import Decision, PermissionManager

TEMPORAL = os.getenv("TEMPORAL_CLI_PATH")  # None = SDK downloads the dev server
WS = tempfile.mkdtemp()

def call(tool_name, **args):
    return {"id": f"c-{uuid.uuid4().hex[:6]}", "name": tool_name, "arguments": args}

SCRIPTS = {
    "A": [
        [call("activate_skill", name="team-board")],
        [call("write_file", path="notes.txt", content="hello")],
        [call("delegate_parallel", tasks=[
            {"agent": "code-reviewer", "task": "TAG:REV review it"},
            {"agent": "api-tester", "task": "TAG:API test it"},
        ])],
        "main done",
    ],
    "REV": ["SLEEP", "review ok"],
    "API": ["SLEEP", "api ok"],
    "B": [[call("write_file", path="b.txt", content="durable")], "B done"],
}
llm_calls: dict[str, int] = {}
timings: dict[str, list[float]] = {}
lock = threading.Lock()
# Fixed call ids per (tag, step) so replays/retries see identical tool calls.
fixed: dict[tuple, list] = {}

@activity.defn(name="llm_complete")
def fake_llm(req: LLMRequest) -> LLMResult:
    users = " ".join(str(m.get("content")) for m in req.history if m["role"] == "user")
    tag = re.search(r"TAG:(\w+)", users).group(1)
    step = sum(1 for m in req.history if m["role"] == "assistant" and "tool_calls" in m)
    with lock:
        llm_calls[f"{tag}:{step}"] = llm_calls.get(f"{tag}:{step}", 0) + 1
    item = SCRIPTS[tag][step]
    if item == "SLEEP":
        timings.setdefault(tag, []).append(time.time())
        time.sleep(1.5)
        timings[tag].append(time.time())
        return LLMResult(content="", tool_calls=[call("read_file", path="notes.txt")], input_tokens=1, output_tokens=1)
    if isinstance(item, str):
        return LLMResult(content=item, tool_calls=[], input_tokens=1, output_tokens=1)
    with lock:
        calls = fixed.setdefault((tag, step), item)
    return LLMResult(content="", tool_calls=calls, input_tokens=1, output_tokens=1)

def make_worker(client):
    return worker_mod.build_worker(client, "test-q", activities=[load_agent_setup, fake_llm, run_tool])

def inp(prompt, **kw):
    return AgentInput(workspace=WS, provider="anthropic", model="m", max_iterations=10,
                      max_tokens=100, prompt=prompt, **kw)

async def main():
    env = await WorkflowEnvironment.start_local(dev_server_existing_path=TEMPORAL)
    client = env.client
    try:
        # ── Scenario A: skill, approval via the real watcher, parallel sub-agents ──
        async with make_worker(client):
            handle = await client.start_workflow(AgentWorkflow.run, inp("TAG:A build it"),
                                                 id="wf-A", task_queue="test-q")
            pm = PermissionManager()
            asked = []
            pm.check = lambda tool, args, tier=None: (asked.append(tool), Decision.ALLOWED)[1]
            watcher = DurableRunWatcher(client, handle.id, pm)
            await asyncio.wait_for(watcher.wait(handle), 60)
            result = await handle.result()
            assert result.final_text == "main done", result
            assert asked == ["write_file"], asked                 # read_file in children auto-allowed
            assert (Path(WS) / "notes.txt").read_text() == "hello"
            rev, api = timings["REV"], timings["API"]
            assert rev[0] < api[1] and api[0] < rev[1], f"not parallel: {timings}"
            st = await handle.query(AgentWorkflow.status, 0)
            assert [c.agent for c in st.children] == ["code-reviewer", "api-tester"]
            assert all(c.done for c in st.children)
            assert any("skill activated: team-board" in e for e in st.events)
            print("A ok · children:", [c.workflow_id for c in st.children])
            print("   overlap:", round(min(rev[1], api[1]) - max(rev[0], api[0]), 2), "s")
            print("   tokens:", result.input_tokens, result.output_tokens)

        # ── Scenario B: worker dies while waiting for approval; new worker resumes ──
        w1 = make_worker(client)
        t1 = asyncio.create_task(w1.run())
        handle = await client.start_workflow(AgentWorkflow.run, inp("TAG:B write"), id="wf-B", task_queue="test-q")
        for _ in range(50):
            st = await handle.query(AgentWorkflow.status, 0)
            if st.pending:
                break
            await asyncio.sleep(0.2)
        assert st.state == "waiting_for_approval", st
        await w1.shutdown(); await t1                 # "crash": no worker running at all
        print("B worker 1 stopped while waiting:", st.pending[0].tool)
        await handle.signal(AgentWorkflow.decide, ApprovalDecision(call_id=st.pending[0].call_id, allow=True))
        async with make_worker(client):              # brand-new worker picks it up
            result = await asyncio.wait_for(handle.result(), 30)
        assert result.final_text == "B done"
        assert (Path(WS) / "b.txt").read_text() == "durable"
        assert llm_calls["B:0"] == 1, llm_calls       # step 0 replayed from history, not re-called
        print("B ok · LLM calls:", {k: v for k, v in llm_calls.items() if k.startswith("B")})
        print("ALL OK")
    finally:
        await env.shutdown()

asyncio.run(main())
