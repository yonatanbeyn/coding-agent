"""Shell execution tools."""

import os
import shutil
import subprocess
from pathlib import Path


def run_shell(command: str, working_dir: str | None = None, timeout: int = 120) -> dict:
    """Run a shell command and return stdout/stderr/exit_code."""
    cwd = working_dir or os.getcwd()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return {
            "exit_code": result.returncode,
            "output": output.strip(),
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "output": f"Command timed out after {timeout}s",
            "success": False,
        }
    except Exception as e:
        return {"exit_code": -1, "output": str(e), "success": False}


def check_command_exists(command: str) -> dict:
    """Check whether a command is available in the system PATH."""
    path = shutil.which(command)
    if path:
        # Try to get version
        ver_result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version = (ver_result.stdout or ver_result.stderr).strip().splitlines()[0] if ver_result.returncode == 0 else ""
        return {"exists": True, "path": path, "version": version}
    return {"exists": False, "path": None, "version": None}


# Tool schemas (what the LLM sees)

RUN_SHELL_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Shell command to execute",
        },
        "working_dir": {
            "type": "string",
            "description": "Working directory for the command. Defaults to agent workspace.",
        },
        "timeout": {
            "type": "integer",
            "description": "Timeout in seconds. Default 120.",
            "default": 120,
        },
    },
    "required": ["command"],
}

CHECK_COMMAND_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Command name to check (e.g. mvn, java, docker, node, python)",
        }
    },
    "required": ["command"],
}