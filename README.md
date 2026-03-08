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
```

---

## Tools (21 total)

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
/tools         List all available tools
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
└── agent/
    ├── loop.py                  # Agent loop (AgentLoop class)
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
        └── aws.py               # S3, Cost Explorer, EC2
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
