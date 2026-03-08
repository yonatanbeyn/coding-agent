"""Tool registry — maps tool names to implementations and schemas."""

import json
from typing import Any, Callable

from agent.llm.base import ToolDef


class ToolRegistry:
    """Registry of all tools available to the agent."""

    def __init__(self, workspace: str, enable_aws: bool = True):
        self.workspace = workspace
        self._tools: dict[str, ToolDef] = {}
        self._register_all(enable_aws)

    def _register_all(self, enable_aws: bool) -> None:
        from agent.tools import shell, files, git, env

        ws = self.workspace

        # ── Shell ──────────────────────────────────────────────────
        self.register(ToolDef(
            name="run_shell",
            description=(
                "Run a shell command in the workspace. Returns stdout, stderr, and exit_code. "
                "Use this for compiling, running servers, curl, wget, or any OS command."
            ),
            parameters=shell.RUN_SHELL_SCHEMA,
            fn=lambda command, working_dir=ws, timeout=120: shell.run_shell(command, working_dir or ws, timeout),
        ))

        self.register(ToolDef(
            name="check_command_exists",
            description="Check if a CLI tool/command is available in the system PATH. Returns exists, path, and version.",
            parameters=shell.CHECK_COMMAND_SCHEMA,
            fn=lambda command: shell.check_command_exists(command),
        ))

        # ── Files ──────────────────────────────────────────────────
        self.register(ToolDef(
            name="read_file",
            description="Read a file and return its content with line numbers. Always read a file before editing it.",
            parameters=files.READ_FILE_SCHEMA,
            fn=lambda path: files.read_file(path, ws),
        ))

        self.register(ToolDef(
            name="write_file",
            description="Create or overwrite a file with the given content. Creates parent directories as needed.",
            parameters=files.WRITE_FILE_SCHEMA,
            fn=lambda path, content: files.write_file(path, content, ws),
        ))

        self.register(ToolDef(
            name="list_files",
            description="List files in a directory. Respects .gitignore when in a git repo.",
            parameters=files.LIST_FILES_SCHEMA,
            fn=lambda path=".", max_depth=3: files.list_files(path, ws, max_depth),
        ))

        self.register(ToolDef(
            name="search_repo",
            description="Search for a regex pattern in files. Returns matching lines with file:line references.",
            parameters=files.SEARCH_REPO_SCHEMA,
            fn=lambda pattern, path=".", file_glob="*": files.search_repo(pattern, path, file_glob, ws),
        ))

        # ── Git ────────────────────────────────────────────────────
        self.register(ToolDef(
            name="git_status",
            description="Show git working tree status (staged, unstaged, untracked files).",
            parameters=git.GIT_STATUS_SCHEMA,
            fn=lambda: git.git_status(ws),
        ))

        self.register(ToolDef(
            name="git_diff",
            description="Show git diff of changes. Pass staged=true to see staged changes.",
            parameters=git.GIT_DIFF_SCHEMA,
            fn=lambda staged=False, path=None: git.git_diff(ws, staged, path),
        ))

        self.register(ToolDef(
            name="git_add",
            description="Stage files for commit. Use ['.'] to stage all changes.",
            parameters=git.GIT_ADD_SCHEMA,
            fn=lambda files: git.git_add(ws, files),
        ))

        self.register(ToolDef(
            name="git_commit",
            description="Create a git commit with the given message.",
            parameters=git.GIT_COMMIT_SCHEMA,
            fn=lambda message: git.git_commit(ws, message),
        ))

        self.register(ToolDef(
            name="git_log",
            description="Show recent git commit history.",
            parameters=git.GIT_LOG_SCHEMA,
            fn=lambda n=10: git.git_log(ws, n),
        ))

        self.register(ToolDef(
            name="git_clone",
            description="Clone a git repository into the workspace.",
            parameters=git.GIT_CLONE_SCHEMA,
            fn=lambda url, dest="": git.git_clone(url, dest, ws),
        ))

        # ── Environment / Dependencies ─────────────────────────────
        self.register(ToolDef(
            name="install_maven",
            description="Install Apache Maven using the system package manager (apt/brew/choco). Auto-detects OS.",
            parameters=env.INSTALL_MAVEN_SCHEMA,
            fn=lambda os=None: env.install_maven(os),
        ))

        self.register(ToolDef(
            name="install_node",
            description="Install Node.js. Uses nvm, brew, or apt depending on OS.",
            parameters=env.INSTALL_NODE_SCHEMA,
            fn=lambda os=None, version="lts": env.install_node(os, version),
        ))

        self.register(ToolDef(
            name="install_python_package",
            description="Install a Python package using pip.",
            parameters=env.INSTALL_PYTHON_PACKAGE_SCHEMA,
            fn=lambda package, upgrade=False: env.install_python_package(package, upgrade),
        ))

        self.register(ToolDef(
            name="install_dependency",
            description="Install any package/tool using the best available package manager (brew/apt/dnf/npm/pip/choco).",
            parameters=env.INSTALL_DEPENDENCY_SCHEMA,
            fn=lambda name, manager=None, os=None: env.install_dependency(name, manager, os),
        ))

        self.register(ToolDef(
            name="run_tests",
            description=(
                "Run the project test suite. Auto-detects the test runner from project files "
                "(Maven, Gradle, npm test, pytest). Pass a custom command to override."
            ),
            parameters=env.RUN_TESTS_SCHEMA,
            fn=lambda command=None, working_dir=None: env.run_tests(command, working_dir or ws),
        ))

        # ── AWS (optional) ─────────────────────────────────────────
        if enable_aws:
            from agent.tools import aws

            self.register(ToolDef(
                name="list_s3_buckets",
                description="List all S3 buckets in the AWS account. Requires AWS credentials.",
                parameters=aws.LIST_S3_SCHEMA,
                fn=lambda: aws.list_s3_buckets(),
            ))

            self.register(ToolDef(
                name="get_aws_billing",
                description="Get AWS billing/cost data for the last N days. Optionally filter by service name.",
                parameters=aws.GET_BILLING_SCHEMA,
                fn=lambda service=None, days=7: aws.get_aws_billing(service, days),
            ))

            self.register(ToolDef(
                name="list_ec2_instances",
                description="List EC2 instances with their state, type, and availability zone.",
                parameters=aws.LIST_EC2_SCHEMA,
                fn=lambda region=None: aws.list_ec2_instances(region),
            ))

            self.register(ToolDef(
                name="get_s3_bucket_size",
                description="Get total size and object count of an S3 bucket.",
                parameters=aws.GET_S3_SIZE_SCHEMA,
                fn=lambda bucket_name: aws.get_s3_bucket_size(bucket_name),
            ))

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def execute(self, name: str, arguments: dict) -> str:
        """Execute a tool by name with given arguments. Returns string result."""
        tool = self.get(name)
        if not tool:
            return json.dumps({"error": f"Unknown tool: {name}"})
        if not tool.fn:
            return json.dumps({"error": f"Tool '{name}' has no implementation"})
        try:
            result = tool.fn(**arguments)
            if isinstance(result, (dict, list)):
                return json.dumps(result, indent=2, default=str)
            return str(result)
        except TypeError as e:
            return json.dumps({"error": f"Invalid arguments for {name}: {e}"})
        except Exception as e:
            return json.dumps({"error": f"Tool execution failed: {e}"})