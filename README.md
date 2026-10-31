# Coding Agent

An AI-powered coding assistant that runs in your terminal. It connects to an LLM (Claude, GPT-4, or a local Ollama model) and uses a tool-calling agent loop to autonomously read files, write code, run shell commands, manage git, install dependencies, and interact with AWS — all with a permission gate before any destructive action.

## How it works

```
User prompt
     │
     ▼
Build context (git status, repo tree, OS)
     │
     ▼
Send prompt + tool schemas → LLM
     │
     ▼
LLM returns tool call(s)
     │
     ▼
Permission check ──── denied ──→ send denial back to LLM
     │ allowed
     ▼
Execute tool (shell / file / git / aws / ...)
     │
     ▼
Send result back → LLM
     │
     ▼
Repeat until LLM stops calling tools
```

The LLM never executes anything directly. It produces structured tool calls; the agent runtime executes them safely.

---

## Two runtimes, same agents

Every agent, skill and agent skill works in both runtimes. You pick the runtime per run:

| | **In-process** (default) | **Durable** (`--durable`, Temporal) |
|---|---|---|
| Start | `python main.py "..."` | `python main.py --worker` once, then `python main.py --durable "..."` |
| Where agents run | Inside your terminal process | In worker processes, as Temporal workflows |
| Sub-agents | Function calls, one at a time | Child workflows, `delegate_parallel` runs them **at the same time** |
| Crash / Ctrl+C / reboot | The run is lost | The run resumes from the last completed step |
| LLM errors (429, 529, timeouts) | Run stops | Retried automatically with backoff |
| Approvals | Prompt blocks the terminal | Durable wait (up to 24h); detach and approve later |
| Streaming output | Yes | No: you see step-by-step progress instead |
| Interactive REPL | Yes | No: one task per run |
| Extra infra | None | A Temporal server (`temporal server start-dev` locally) |

See **[Durable mode (Temporal)](#durable-mode-temporal)** for the full guide.

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your API key
cp .env.example .env
# edit .env → set ANTHROPIC_API_KEY (or OPENAI_API_KEY)

# 3. Run
python main.py                          # interactive REPL
python main.py "Create a Springboot App"    # one-shot task
```

---

## Providers

| Provider | Default model | How to use |
|---|---|---|
| `anthropic` *(default)* | `claude-sonnet-4-6` | Set `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o` | Set `OPENAI_API_KEY` |
| `ollama` | `llama3.2` | Run Ollama locally, no key needed |

```bash
python main.py --provider openai "..."
python main.py --provider ollama --model codestral "..."
python main.py --provider anthropic --model claude-opus-4-6 "..."
```

You can also point at any OpenAI-compatible endpoint (Groq, OpenRouter, vLLM, LM Studio):

```bash
AGENT_BASE_URL=https://api.groq.com/openai/v1 \
AGENT_API_KEY=gsk_... \
python main.py --provider openai --model llama-3.3-70b-versatile "..."
```

---

## CLI flags

```
python main.py [prompt] [flags]

  --provider   anthropic | openai | ollama
  --model      model name (e.g. claude-opus-4-6, gpt-4o, llama3.2)
  --workspace  working directory for the agent (default: current dir)
  --yes / -y   auto-approve all tool calls (skip permission prompts)
  --no-aws     disable AWS tools
  --no-stream  disable streaming output
  --agent      run the session as an agent skill (e.g. --agent code-reviewer)
  --list-skills  list discovered skills and agent skills, then exit
  --worker     run a Temporal worker (durable mode)
  --durable    run the task as a Temporal workflow (needs a running worker)
  --attach ID  re-attach to a durable run: stream progress, answer approvals
```

---

## Skills vs agent skills

This agent can be extended without writing Python, using two kinds of markdown files.
They do different jobs:

| | **Skill** | **Agent skill** |
|---|---|---|
| Defines | *Know-how*: how to do one kind of task | *An agent*: who does the work |
| File | `<name>/SKILL.md` folder (+ `scripts/`, `reference/`, `assets/`) | One `<name>.md` file |
| Body is | Instructions loaded into the **current** agent | The **system prompt** of a separate agent |
| Controls | Which gated tools get unlocked (`allowed-tools`) | Tool allowlist (`tools`), usable skills (`skills`), `model`, `max-iterations` |
| Context | Shares the current conversation | Gets its own fresh conversation; returns only its final answer |
| How it is used | The model calls `activate_skill(name)` | The model calls `delegate_to_agent(agent, task)`, or you start with `--agent NAME` |
| Example | `desktop-gui`: how to drive Postman safely | `api-tester`: an agent that finds routes and tests them, *using* the `desktop-gui` skill |
| Compatible with | Agent Skills spec: Claude Code, GitHub Copilot skills | Claude Code subagents, GitHub Copilot custom agents |

In one sentence: **a skill is something an agent knows; an agent skill is an agent.**
Agent skills can list the skills they are allowed to use, so agents are composed from skills.

```
Main agent (config.SYSTEM_PROMPT + catalogs)
 ├─ activate_skill("aws-inventory")        → instructions loaded here, AWS tools unlocked
 └─ delegate_to_agent("api-tester", task)  → new AgentLoop with api-tester.md as its prompt
       └─ activate_skill("desktop-gui")    → allowed because api-tester lists it in `skills:`
```

### Where they are discovered

The first one found wins, so project files override user files, and user files override bundled ones.

| Scope | Skills | Agent skills |
|---|---|---|
| Project (workspace) | `.agents/skills/`, `.claude/skills/`, `.github/skills/` | `.agents/agents/`, `.claude/agents/`, `.github/agents/` (`*.md`, `*.agent.md`) |
| User | `~/.agents/skills/`, `~/.claude/skills/`, `~/.copilot/skills/` | `~/.agents/agents/`, `~/.claude/agents/`, `~/.copilot/agents/` |
| Bundled | `skills/` in this repo | `agents/` in this repo |

Project-scope skills and agent skills may come from a repository you just cloned, so
activating or delegating to one always asks for permission first. Every tool call a skill or
sub-agent makes still goes through the normal permission gate.

### Writing a skill

```markdown
---
name: aws-inventory                 # lowercase-hyphen
description: Inspect an AWS account... Use when the user asks about AWS resources or billing.
allowed-tools: list_s3_buckets get_aws_billing   # gated tools this skill unlocks
---
# Instructions the agent follows after activating the skill
```

Only `name` and `description` sit in the system prompt (the catalog). The body is loaded
when the model calls `activate_skill`, and files under the skill's folder are read only when the
body points to them. GUI and AWS tools are **gated**: they're hidden from the model until
a skill that lists them in `allowed-tools` is activated.

### Writing an agent skill

```markdown
---
name: code-reviewer
description: Reviews changes for bugs without editing. Use after code changes.
tools: read_file, search_repo, git_diff   # omit = all tools (list or comma string)
skills: []                                # omit = all skills, [] = none
model: inherit                            # or sonnet / opus / haiku / any model id
max-iterations: 25
---
You are a senior code reviewer...         # this body is the agent's system prompt
```

### Multi-agent teams

Delegation goes up to two levels: **main agent → team lead → workers**. Below the top
level, only agent skills that list `delegate_to_agent` in `tools` can delegate. An agent never
sees itself or its callers in its catalog, so A → B → A loops are impossible.

Each agent gets its own conversation, LLM client, model and tool allowlist. Teammates share
nothing except the `task` text, their final answer, and the workspace files. The
`team-board` skill turns those files into shared memory (`.agent-team/<feature>/board.json`
and `board.md`).

Bundled example team:

```
feature-lead   (plans on the board, delegates, loops review → fix; never writes code)
 ├─ implementer    (writes code + tests for one task)
 ├─ code-reviewer  (read-only review)
 └─ api-tester     (curl / Postman checks)
```

```bash
python main.py --agent feature-lead "Add a /health endpoint with a test"
python main.py "Add user login with tests"     # main agent can delegate to feature-lead
```

Delegation tools available to agents that can delegate:

| Tool | In-process runtime | Durable runtime |
|---|---|---|
| `delegate_to_agent(agent, task)` | Runs the sub-agent, waits for its answer | Child workflow, waits for its answer |
| `delegate_parallel(tasks=[...])` (max 5) | Runs the tasks **one after another** | Child workflows running **at the same time** |

Agents never message each other directly. Only the task goes down and the final answer
comes back up; anything else goes through workspace files such as the team board.

---

## Durable mode (Temporal)

Durable mode runs the same agents as [Temporal](https://temporal.io) workflows. Use it for
long tasks, agent teams, parallel sub-agents, or anything you don't want to lose to a crash,
a closed laptop or an LLM outage.

### Quick start

```bash
pip install -r requirements.txt            # includes temporalio

# Terminal 1: a local Temporal server (UI at http://localhost:8233)
temporal server start-dev --db-filename temporal.db   # install: brew install temporal (docs.temporal.io/cli)

# Terminal 2: a worker. It executes LLM calls and tools, so run it where the workspace is
python main.py --worker

# Terminal 3: start a task
python main.py --durable "Add a /health endpoint with a test"
python main.py --durable --agent feature-lead "Add user login with tests"
python main.py --durable --yes "..."       # never wait for approvals

# Ctrl+C detaches; the run keeps going. Re-attach any time:
python main.py --attach coding-agent-1a2b3c4d
```

### Architecture

```
 ┌──────────────────────┐   start / query / signal   ┌──────────────────────────┐
 │  Client (terminal)   │ ─────────────────────────▶ │     Temporal server      │
 │  main.py --durable   │ ◀───────────────────────── │  event history per run   │
 │  main.py --attach    │   status, pending approvals│  timers, retries, queues │
 └──────────────────────┘                            └────────────┬─────────────┘
   • prints progress of every agent                               │ task queue
   • asks you to approve tools                                    │ "coding-agent"
   • holds NO agent state (safe to close)                         ▼
                                              ┌────────────────────────────────────┐
                                              │  Worker  (main.py --worker)        │
                                              │                                    │
                                              │  AgentWorkflow  (deterministic)    │
                                              │    the agent loop: decide next step│
                                              │                                    │
                                              │  Activities  (side effects)        │
                                              │    load_agent_setup  skills/agents │
                                              │    llm_complete      model call    │
                                              │    run_tool          shell/files/… │
                                              │                                    │
                                              │  thread pool: N activities at once │
                                              └──────────────┬─────────────────────┘
                                                             │
                                          workspace files, git, shell, AWS, desktop
```

Temporal records the result of every activity in the run's **event history**. If a worker
dies, another worker (or the same one after a restart) replays the history: completed LLM
calls and tools are *not* repeated, and the agent continues from the exact step it was on.
API keys stay in the worker's environment and never appear in the history.

### How one agent runs

```
AgentWorkflow.run(AgentInput)
 │
 ├─ activity load_agent_setup ──▶ agent skill + skills + delegation targets + system prompt
 │
 └─ loop (max_iterations)
      │
      ├─ activity llm_complete ──▶ retried with backoff (2s → 1m, 6 attempts)
      │
      ├─ no tool calls? ──▶ return AgentResult(final_text, steps, tokens)
      │
      └─ for each tool call
           ├─ activate_skill      handled in the workflow: unlock tools, return SKILL.md body
           ├─ delegate_to_agent   ──▶ child AgentWorkflow, wait for its result
           ├─ delegate_parallel   ──▶ up to 5 child AgentWorkflows, gathered concurrently
           └─ any other tool
                ├─ needs approval? ──▶ pending approval, wait for `decide` signal (≤ 24h)
                └─ activity run_tool ──▶ executed ONCE (no retry: tools have side effects)
```

### A team run: parallel sub-agents as child workflows

```
coding-agent-1a2b3c4d                         main agent          (depth 0)
 └─ coding-agent-1a2b3c4d.1-feature-lead      team lead           (depth 1)
     ├─ ….1-feature-lead.1-implementer        worker              (depth 2)
     │
     │   delegate_parallel ─────────────────────────┐
     ├─ ….1-feature-lead.2-code-reviewer   ◀─┐      │  started together,
     └─ ….1-feature-lead.3-api-tester      ◀─┴──────┘  lead waits for both

time ─────────────────────────────────────────────────────────────▶
lead          plan ── implementer ─────── gather( reviewer , tester ) ── report
implementer         ███████████
code-reviewer                           ██████████
api-tester                              ████████████████
```

Workflow IDs are deterministic: `<parent id>.<n>-<agent name>`. Each one appears in the
Temporal UI with its full history of LLM calls, tool calls, approvals and results.

### Approvals

The permission tiers are the same as in-process (auto-allow, ask, deny; project-scope skills
and agent skills always ask). In durable mode, an "ask" becomes a durable wait:

```
 AgentWorkflow (any depth)            Temporal                  Client (--durable / --attach)
 ─────────────────────────            ────────                  ─────────────────────────────
 tool needs approval
 pending[call_id] = {tool, args}
 state = waiting_for_approval
 wait_condition(decided) ─────┐                                 every 1s: query status
         (durable, ≤ 24h)     │  ◀─── query status ───────────  walks main → children tree
                              │  ──── pending approvals ──────▶ shows tool + arguments
                              │                                 Allow? (y/a/n/d)
                              │  ◀─── signal decide(call_id) ── 
 decision received ◀──────────┘
 run_tool or report denial to the LLM
```

- **No client attached?** The agent just waits. Attach later and answer the prompt.
- **"Always allow" / "always deny"** are remembered by the client for that session.
- **No answer in 24h** means the call is denied, and the agent is told so.
- **`--yes`** skips all approvals; use it only in sandboxes.

### Crash and restart behaviour

| What happens | Result |
|---|---|
| You press Ctrl+C in the client | Client detaches. Agents keep running. `--attach <id>` to resume watching |
| Client machine sleeps or reboots | Same as above |
| Worker process crashes / is restarted | Run resumes on the next available worker from the last completed step |
| Worker dies **during** a tool | That tool is not re-run automatically. The agent is told it didn't complete and decides what to do |
| LLM API returns 429/529/5xx or times out | Retried up to 6 times with exponential backoff, then the agent stops with the error |
| Temporal server restarts | Runs continue, because the server persists history. `temporal server start-dev` keeps it in memory unless you pass `--db-filename temporal.db` |

### Scaling and placement

```
                    ┌────────── Temporal server ──────────┐
                    │  task queue: coding-agent           │
                    └───────┬──────────────┬──────────────┘
                            │              │
                ┌───────────▼───┐   ┌──────▼────────┐
                │ worker A      │   │ worker B      │   same queue = shared load,
                │ (your Mac)    │   │ (build box)   │   failover between them
                └───────────────┘   └───────────────┘
```

- **Workspace access:** tools act on the worker's filesystem, so every worker on a queue
  must see the workspace at the same path (same machine, or a shared/cloned checkout).
- **GUI skills** (`desktop-gui`) must run on the Mac whose screen they control. Give that
  machine its own queue (`TEMPORAL_TASK_QUEUE=my-mac`) and start runs on it.
- **Concurrency:** `TEMPORAL_MAX_CONCURRENT_ACTIVITIES` (default 10) caps how many LLM calls
  and tools one worker runs at once across all parallel sub-agents.
- **Parallel agents share one workspace.** Only send independent tasks to
  `delegate_parallel`, never two agents editing the same files, and never two GUI tasks at once.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TEMPORAL_ADDRESS` | `localhost:7233` | Temporal frontend (`<ns>.tmprl.cloud:7233` for Temporal Cloud) |
| `TEMPORAL_NAMESPACE` | `default` | Namespace |
| `TEMPORAL_TASK_QUEUE` | `coding-agent` | Queue that workers poll and runs are started on |
| `TEMPORAL_MAX_CONCURRENT_ACTIVITIES` | `10` | Activities one worker runs in parallel |

Provider settings (`AGENT_PROVIDER`, `AGENT_MODEL`, API keys) are read by the **client**
(to choose provider and model for the run) and by the **worker** (for the API key).

### Limits

- **One task per run.** No interactive REPL and no follow-up messages in durable mode yet.
- **No token streaming.** You see each step as it completes.
- **History size.** The whole conversation is passed to each `llm_complete` call, so very
  long runs grow the event history (Temporal's limits are 2 MB per payload and 50 MB per
  run). Use `--max-iterations` and break big jobs into a team.
- **Delegation depth** is 2 (main → lead → workers), the same as in-process.

### Testing

`tests/test_durable.py` runs the real workflow, activities and client watcher against a local
Temporal dev server, using a scripted fake LLM (no API key needed). It checks that parallel
sub-agents overlap in time and that a run survives its worker being stopped mid-run:

```bash
python tests/test_durable.py                         # SDK downloads the dev server
TEMPORAL_CLI_PATH=$(which temporal) python tests/test_durable.py
```

### Code map

```
agent/durable/
├── workflow.py    AgentWorkflow: deterministic loop, approvals, child workflows, status query
├── activities.py  load_agent_setup · llm_complete · run_tool  (all I/O lives here)
├── worker.py      Worker setup: sandbox pass-through, thread pool          (--worker)
├── client.py      start / attach, progress tree, approval prompts          (--durable, --attach)
└── types.py       dataclass payloads stored in workflow history
agent/capabilities.py   shared by both runtimes: agent skill → config, skills, delegation, meta-tools
tests/test_durable.py   end-to-end test against a local Temporal dev server
```

---

## Tools

GUI and AWS tools are gated behind the `desktop-gui` and `aws-inventory` skills (see above).


### Shell
| Tool | Description |
|---|---|
| `run_shell` | Run any shell command |
| `check_command_exists` | Check if a CLI tool is in PATH (returns version) |

### Files
| Tool | Description |
|---|---|
| `read_file` | Read a file with line numbers |
| `write_file` | Create or overwrite a file |
| `list_files` | List directory contents (respects .gitignore) |
| `search_repo` | Regex search across files |

### Git
| Tool | Description |
|---|---|
| `git_status` | Show working tree status |
| `git_diff` | Show unstaged or staged changes |
| `git_add` | Stage files |
| `git_commit` | Create a commit |
| `git_log` | Show recent commit history |
| `git_clone` | Clone a repository |

### Environment & Dependencies
| Tool | Description |
|---|---|
| `install_maven` | Install Apache Maven (auto-detects apt/brew/choco) |
| `install_node` | Install Node.js (nvm/brew/apt) |
| `install_python_package` | Install a pip package |
| `install_dependency` | Install anything via best available package manager |
| `run_tests` | Run tests (auto-detects Maven/Gradle/npm/pytest) |

### AWS
| Tool | Description |
|---|---|
| `list_s3_buckets` | List all S3 buckets |
| `get_aws_billing` | Get cost data from Cost Explorer |
| `list_ec2_instances` | List EC2 instances with state/type |
| `get_s3_bucket_size` | Get total size and object count of a bucket |

---

## Permission system

Before any write, execute, or network tool runs, the agent asks for confirmation — just like Claude Code does.

```
┌─ Tool request ──────────────────────────────────
  run_shell
  {
    "command": "mvn package"
  }
└────────────────────────────────────────────────
  (y) yes  (a) always allow  (n) no  (d) always deny  (q) abort
  Allow?
```

| Key | Behaviour |
|---|---|
| `y` | Allow this one call |
| `a` | Always allow this tool for the session |
| `n` | Deny this call — LLM is told the user refused |
| `d` | Always deny this tool for the session |
| `q` | Abort |

**Safe tools** (read-only) run silently without a prompt:
`read_file`, `list_files`, `search_repo`, `check_command_exists`, `git_status`, `git_diff`, `git_log`

**All other tools** prompt before running.

Use `--yes` / `-y` to skip all prompts (useful for scripted/CI usage).

---

## Interactive REPL commands

```
/tools         List all tools (hidden ones are marked)
/skills        List skills — /skills reload re-scans the folders
/agents        List agent skills available for delegation
/permissions   Show always-allowed / always-denied tools this session
/tokens        Show token usage so far
/history       Show conversation history
/workspace     Show current workspace path
/clear         Reset conversation (keeps permissions)
/exit          Quit
```

---

## Project structure

```
coding-agent/
├── main.py                      # CLI entry point
├── config.py                    # Config dataclass (env-driven)
├── requirements.txt
├── .env.example
├── skills/                      # Bundled skills (know-how): <name>/SKILL.md
│   ├── desktop-gui/
│   ├── aws-inventory/
│   └── team-board/              # shared task board for agent teams (with a script)
├── agents/                      # Bundled agent skills (agents): <name>.md
│   ├── feature-lead.md          # team lead: plans + delegates
│   ├── implementer.md
│   ├── code-reviewer.md
│   └── api-tester.md
└── agent/
    ├── loop.py                  # In-process agent loop (AgentLoop); default agent or an agent skill
    ├── capabilities.py          # Shared by both runtimes: setup, catalogs, meta-tools
    ├── durable/                 # Temporal runtime: workflow, activities, worker, client
    ├── skills.py                # Skill discovery, catalog
    ├── agent_skills.py          # Agent skill discovery, catalog, model aliases
    ├── frontmatter.py           # Shared YAML frontmatter parser
    ├── context.py               # Builds workspace context for the LLM
    ├── permissions.py           # Permission gate (ask/auto/deny tiers)
    ├── llm/
    │   ├── base.py              # Shared types: ToolDef, ToolCall, LLMResponse
    │   ├── anthropic_client.py  # Anthropic Claude provider
    │   └── openai_client.py     # OpenAI / Ollama / Groq / OpenRouter provider
    └── tools/
        ├── registry.py          # Wires all tools together
        ├── shell.py             # run_shell, check_command_exists
        ├── files.py             # read_file, write_file, list_files, search_repo
        ├── git.py               # git_status/diff/add/commit/log/clone
        ├── env.py               # install_maven/node/python_package, run_tests
        ├── aws.py               # S3, Cost Explorer, EC2 (gated)
        └── gui.py               # Desktop automation (gated)
```

---

## Configuration via `.env`

```bash
# Provider
AGENT_PROVIDER=anthropic          # anthropic | openai | ollama
AGENT_MODEL=claude-sonnet-4-6

# Keys
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
AGENT_BASE_URL=                   # custom endpoint (Ollama, Groq, etc.)

# Behaviour
AGENT_WORKSPACE=                  # default: current directory
AGENT_MAX_ITERATIONS=50
AGENT_STREAM=true

# AWS (or use ~/.aws/credentials)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=us-east-1

# Durable mode (Temporal)
TEMPORAL_ADDRESS=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=coding-agent
TEMPORAL_MAX_CONCURRENT_ACTIVITIES=10
```

---

## Example sessions

**Build a Spring Boot app**
```
You> Create a Spring Boot app with a /hello endpoint
```
The agent will: check if Maven/Java exist → install if missing → scaffold the project → write pom.xml + controller → run `mvn package` → verify with curl.

**AWS audit**
```
You> List my S3 buckets and show billing for the last 7 days
```

**Fix a failing test**
```
You> The tests in ./auth are failing, find and fix the issue
```

---

## Requirements

- Python 3.11+
- At least one of: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or Ollama running locally
- AWS tools require `boto3` and configured AWS credentials (optional)
- Durable mode requires `temporalio` and a Temporal server: `temporal server start-dev`
  locally, a self-hosted cluster, or Temporal Cloud (optional)
