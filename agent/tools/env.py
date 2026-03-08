"""Environment & dependency management tools.

Handles detection and installation of build tools: Maven, Node, Python packages,
Docker, and generic package manager installs.
"""

import platform
import shutil
import subprocess
import sys


def _detect_os() -> str:
    s = platform.system().lower()
    if "linux" in s:
        return "linux"
    if "darwin" in s:
        return "mac"
    if "windows" in s:
        return "windows"
    return "unknown"


def _run(cmd: str | list, shell: bool = True) -> dict:
    if isinstance(cmd, list):
        shell = False
    result = subprocess.run(
        cmd,
        shell=shell,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return {
        "exit_code": result.returncode,
        "output": (result.stdout + result.stderr).strip(),
        "success": result.returncode == 0,
    }


def install_maven(os_name: str | None = None) -> dict:
    """Install Apache Maven using the system package manager."""
    os_name = os_name or _detect_os()
    if os_name == "linux":
        return _run("sudo apt-get update && sudo apt-get install -y maven")
    if os_name == "mac":
        return _run("brew install maven")
    if os_name == "windows":
        return _run("choco install maven -y", shell=False)
    return {"exit_code": 1, "output": f"Unsupported OS: {os_name}", "success": False}


def install_node(os_name: str | None = None, version: str = "lts") -> dict:
    """Install Node.js. Uses nvm when possible."""
    os_name = os_name or _detect_os()
    if os_name in ("linux", "mac"):
        # Try nvm first
        if shutil.which("nvm"):
            return _run(f"nvm install {version} && nvm use {version}")
        if shutil.which("brew") and os_name == "mac":
            return _run("brew install node")
        return _run("curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs")
    if os_name == "windows":
        return _run("choco install nodejs-lts -y", shell=False)
    return {"exit_code": 1, "output": f"Unsupported OS: {os_name}", "success": False}


def install_python_package(package: str, upgrade: bool = False) -> dict:
    """Install a Python package using pip."""
    cmd = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        cmd.append("--upgrade")
    cmd.append(package)
    return _run(cmd)


def install_dependency(name: str, manager: str | None = None, os_name: str | None = None) -> dict:
    """Generic dependency installer. Auto-detects package manager if not specified."""
    os_name = os_name or _detect_os()

    # Infer manager from available tools
    if manager is None:
        if shutil.which("brew"):
            manager = "brew"
        elif shutil.which("apt-get"):
            manager = "apt"
        elif shutil.which("dnf"):
            manager = "dnf"
        elif shutil.which("pip") or shutil.which("pip3"):
            manager = "pip"
        elif shutil.which("npm"):
            manager = "npm"
        elif shutil.which("choco"):
            manager = "choco"
        else:
            return {"exit_code": 1, "output": "Could not detect package manager", "success": False}

    commands = {
        "brew": f"brew install {name}",
        "apt": f"sudo apt-get install -y {name}",
        "apt-get": f"sudo apt-get install -y {name}",
        "dnf": f"sudo dnf install -y {name}",
        "pip": f"pip install {name}",
        "pip3": f"pip3 install {name}",
        "npm": f"npm install -g {name}",
        "choco": f"choco install {name} -y",
    }

    cmd = commands.get(manager)
    if not cmd:
        return {"exit_code": 1, "output": f"Unknown manager: {manager}", "success": False}

    return _run(cmd)


def run_tests(command: str | None = None, working_dir: str | None = None) -> dict:
    """Run the project test suite. Auto-detects test runner if command not given."""
    import os
    cwd = working_dir or os.getcwd()

    if command:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=cwd, timeout=300)
        return {
            "exit_code": result.returncode,
            "output": (result.stdout + result.stderr).strip(),
            "success": result.returncode == 0,
        }

    # Auto-detect
    detectors = [
        (lambda: (cwd + "/pom.xml"), "./mvnw test" if shutil.which("./mvnw") else "mvn test"),
        (lambda: (cwd + "/build.gradle"), "./gradlew test" if shutil.which("./gradlew") else "gradle test"),
        (lambda: (cwd + "/package.json"), "npm test"),
        (lambda: (cwd + "/pyproject.toml"), "pytest"),
        (lambda: (cwd + "/setup.py"), "pytest"),
        (lambda: (cwd + "/Makefile"), "make test"),
        (lambda: True, "pytest"),
    ]

    for check, cmd in detectors:
        try:
            if check():
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=300)
                return {
                    "exit_code": result.returncode,
                    "output": (result.stdout + result.stderr).strip(),
                    "success": result.returncode == 0,
                    "detected_runner": cmd,
                }
        except Exception:
            continue

    return {"exit_code": 1, "output": "Could not detect test runner", "success": False}


# Schemas

INSTALL_MAVEN_SCHEMA = {
    "type": "object",
    "properties": {
        "os": {"type": "string", "description": "OS: linux, mac, windows. Auto-detected if omitted."},
    },
}

INSTALL_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "os": {"type": "string", "description": "OS: linux, mac, windows. Auto-detected if omitted."},
        "version": {"type": "string", "description": "Node version or 'lts'. Default: lts", "default": "lts"},
    },
}

INSTALL_PYTHON_PACKAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "package": {"type": "string", "description": "Package name (e.g. requests, flask, pytest)"},
        "upgrade": {"type": "boolean", "description": "Upgrade if already installed", "default": False},
    },
    "required": ["package"],
}

INSTALL_DEPENDENCY_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Package/tool name to install"},
        "manager": {
            "type": "string",
            "description": "Package manager: brew, apt, dnf, pip, npm, choco. Auto-detected if omitted.",
            "enum": ["brew", "apt", "apt-get", "dnf", "pip", "pip3", "npm", "choco"],
        },
        "os": {"type": "string", "description": "OS hint: linux, mac, windows"},
    },
    "required": ["name"],
}

RUN_TESTS_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Test command to run. Auto-detected if omitted."},
        "working_dir": {"type": "string", "description": "Directory to run tests in. Default: workspace root."},
    },
}