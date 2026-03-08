#!/usr/bin/env python3
"""
Coding Agent — AI-powered development assistant.

Usage:
  python main.py                             # interactive REPL
  python main.py "Create a Flask REST API"  # one-shot task
  python main.py --provider openai "..."    # use OpenAI
  python main.py --provider ollama "..."    # use local Ollama
"""

import argparse
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config import Config
from agent.loop import AgentLoop


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Coding Agent — AI-powered development assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                                   Launch interactive REPL
  python main.py "Build a Flask health endpoint"  One-shot task
  python main.py --provider openai                 Use OpenAI GPT-4o
  python main.py --provider ollama --model llama3.2  Use local Ollama
  python main.py --workspace /path/to/project      Set working directory
  python main.py --no-aws "..."                    Disable AWS tools
        """,
    )

    parser.add_argument(
        "prompt",
        nargs="*",
        help="Task to perform (no quotes needed). If omitted, launches interactive REPL.",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai", "ollama"],
        help="LLM provider (default: anthropic)",
    )
    parser.add_argument(
        "--model",
        help="Model name (e.g. claude-sonnet-4-6, gpt-4o, llama3.2)",
    )
    parser.add_argument(
        "--workspace",
        help="Working directory for the agent (default: current directory)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="Max tool-call iterations per request (default: 50)",
    )
    parser.add_argument(
        "--no-aws",
        action="store_true",
        help="Disable AWS tools",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming output",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Auto-approve all tool calls without prompting (use with caution)",
    )

    args = parser.parse_args()

    config = Config.from_env()

    if args.provider:
        config.provider = args.provider
        # Apply sensible model defaults when provider is explicitly changed
        if not args.model:
            defaults = {"anthropic": "claude-sonnet-4-6", "openai": "gpt-4o", "ollama": "llama3.2"}
            config.model = defaults.get(args.provider, config.model)

    if args.model:
        config.model = args.model

    if args.workspace:
        path = os.path.abspath(args.workspace)
        if not os.path.isdir(path):
            print(f"Error: workspace directory does not exist: {path}", file=sys.stderr)
            sys.exit(1)
        config.workspace = path

    if args.max_iterations:
        config.max_iterations = args.max_iterations

    if args.no_stream:
        config.stream = False

    agent = AgentLoop(config, enable_aws=not args.no_aws, auto_allow_all=args.yes)

    if args.prompt:
        agent.run(" ".join(args.prompt))
    else:
        agent.interactive()


if __name__ == "__main__":
    main()