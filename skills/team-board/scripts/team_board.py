#!/usr/bin/env python3
"""Shared task board for a team of agents.

Agents in a team run in separate contexts and cannot see each other's
conversations. The board is their shared memory: a JSON file in the workspace
(plus a rendered markdown view) that every agent can read and update.

Usage:
  team_board.py init   <feature> "<goal>"
  team_board.py add    <feature> "<title>" [--owner AGENT] [--depends-on ID,...]
  team_board.py update <feature> <id> [--status todo|doing|review|done|blocked]
                                      [--owner AGENT] [--note "text"]
  team_board.py show   <feature>
  team_board.py next   <feature>           # first todo task whose dependencies are done

Run from the workspace root. Files live in .agent-team/<feature>/.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ["todo", "doing", "review", "done", "blocked"]
ROOT = Path(".agent-team")


def _paths(feature: str) -> tuple[Path, Path]:
    folder = ROOT / feature
    return folder / "board.json", folder / "board.md"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _load(feature: str) -> dict:
    board_json, _ = _paths(feature)
    if not board_json.exists():
        sys.exit(json.dumps({"error": f"No board for {feature!r}. Run: init {feature} \"<goal>\""}))
    return json.loads(board_json.read_text())


def _save(board: dict) -> None:
    board_json, board_md = _paths(board["feature"])
    board_json.parent.mkdir(parents=True, exist_ok=True)
    board_json.write_text(json.dumps(board, indent=2))
    board_md.write_text(_render(board))


def _render(board: dict) -> str:
    lines = [f"# {board['feature']}", "", f"**Goal:** {board['goal']}", "",
             "| ID | Task | Owner | Status | Depends on |", "|---|---|---|---|---|"]
    for t in board["tasks"]:
        deps = ", ".join(map(str, t["depends_on"])) or "-"
        lines.append(f"| {t['id']} | {t['title']} | {t['owner'] or '-'} | {t['status']} | {deps} |")
    lines += ["", "## Log", ""]
    lines += [f"- {e['at']} · task {e['task']} · {e['text']}" for e in board["log"]]
    return "\n".join(lines) + "\n"


def _task(board: dict, task_id: int) -> dict:
    for t in board["tasks"]:
        if t["id"] == task_id:
            return t
    sys.exit(json.dumps({"error": f"No task {task_id}"}))


def cmd_init(a) -> dict:
    board_json, _ = _paths(a.feature)
    if board_json.exists():
        return {"error": f"Board {a.feature!r} already exists", "board": str(board_json)}
    board = {"feature": a.feature, "goal": a.goal, "tasks": [], "log": []}
    _save(board)
    return {"created": str(board_json)}


def cmd_add(a) -> dict:
    board = _load(a.feature)
    deps = [int(d) for d in a.depends_on.split(",")] if a.depends_on else []
    for d in deps:
        _task(board, d)
    task = {"id": len(board["tasks"]) + 1, "title": a.title, "owner": a.owner,
            "status": "todo", "depends_on": deps}
    board["tasks"].append(task)
    _save(board)
    return {"added": task}


def cmd_update(a) -> dict:
    board = _load(a.feature)
    task = _task(board, a.id)
    if a.status:
        task["status"] = a.status
    if a.owner:
        task["owner"] = a.owner
    text = " · ".join(x for x in [a.status and f"status → {a.status}", a.note] if x)
    if text:
        board["log"].append({"at": _now(), "task": a.id, "text": text})
    _save(board)
    return {"updated": task}


def cmd_show(a) -> dict:
    board = _load(a.feature)
    counts = {s: sum(t["status"] == s for t in board["tasks"]) for s in STATUSES}
    return {"goal": board["goal"], "counts": counts, "tasks": board["tasks"],
            "recent_log": board["log"][-10:]}


def cmd_next(a) -> dict:
    board = _load(a.feature)
    done = {t["id"] for t in board["tasks"] if t["status"] == "done"}
    for t in board["tasks"]:
        if t["status"] == "todo" and set(t["depends_on"]) <= done:
            return {"next": t}
    remaining = [t for t in board["tasks"] if t["status"] != "done"]
    return {"next": None, "all_done": not remaining, "remaining": remaining}


def main() -> None:
    p = argparse.ArgumentParser(description="Shared task board for an agent team")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("feature"); s.add_argument("goal")
    s = sub.add_parser("add"); s.add_argument("feature"); s.add_argument("title")
    s.add_argument("--owner"); s.add_argument("--depends-on")
    s = sub.add_parser("update"); s.add_argument("feature"); s.add_argument("id", type=int)
    s.add_argument("--status", choices=STATUSES); s.add_argument("--owner"); s.add_argument("--note")
    sub.add_parser("show").add_argument("feature")
    sub.add_parser("next").add_argument("feature")

    a = p.parse_args()
    result = {"init": cmd_init, "add": cmd_add, "update": cmd_update,
              "show": cmd_show, "next": cmd_next}[a.cmd](a)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
