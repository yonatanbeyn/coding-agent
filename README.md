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

Sub-agents can't delegate further (one level deep). An agent skill started with `--agent`
can delegate only if it lists `delegate_to_agent` in `tools`.

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
│   └── aws-inventory/
├── agents/                      # Bundled agent skills (agents): <name>.md
│   ├── code-reviewer.md
│   └── api-tester.md
└── agent/
    ├── loop.py                  # Agent loop (AgentLoop class); runs default agent or an agent skill
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
