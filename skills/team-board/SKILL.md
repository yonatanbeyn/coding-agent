---
name: team-board
description: Shared task board that lets a team of agents coordinate across separate contexts — create a plan, assign tasks, record progress and hand off work through files in .agent-team/. Use when working as part of a multi-agent team, or when splitting a feature into tasks for several agents.
compatibility: Requires python3 on PATH. Writes to .agent-team/ in the workspace.
---

# Team board

Agents in a team do not share a conversation. Each sub-agent starts with an empty
context and only sees the `task` text it was given. The board is the team's shared
memory: one file per feature that every agent reads before working and updates after.

The script is `scripts/team_board.py` inside this skill's `base_dir`. Run it with
`run_shell` from the workspace root:

```
python <base_dir>/scripts/team_board.py <command> <feature> ...
```

| Command | Purpose |
|---|---|
| `init <feature> "<goal>"` | Create the board (lead only, once) |
| `add <feature> "<title>" --owner AGENT --depends-on 1,2` | Add a task |
| `update <feature> <id> --status doing\|review\|done\|blocked --note "..."` | Record progress |
| `show <feature>` | Read the whole board as JSON |
| `next <feature>` | First `todo` task whose dependencies are all `done` |

`<feature>` is a short kebab-case slug, e.g. `user-login`. People can read
`.agent-team/<feature>/board.md` while the team works.

## If you are the team lead
1. `init` the board with the user's goal in one sentence.
2. Break the work into small tasks (each one a single agent can finish), `add` each with
   an `--owner` from the agent skills catalog and `--depends-on` where order matters.
3. Loop: `next` → `update --status doing` → `delegate_to_agent(owner, task)` →
   record the result with `update --status done|review|blocked --note "<summary>"`.
4. The `task` you delegate must be self-contained. Always include: the feature slug,
   the task id, what "done" means, and the line
   "Read the team board with team-board `show` first and update your task when finished."
5. Stop when `next` returns `all_done: true`, or when a task is `blocked` and needs the user.

## If you are a team member
1. Run `show <feature>` first to see the goal, what is already done and any notes.
2. Do only your task. Do not start other tasks on the board.
3. When finished, run `update <feature> <id> --status done --note "<what changed, files touched>"`.
   If you cannot finish, use `--status blocked` and say exactly what is missing.

## Rules
- Notes are for the next agent: name files, commands and decisions, not chit-chat.
- Never delete or rewrite other agents' log entries.
- Suggest adding `.agent-team/` to `.gitignore` unless the user wants the board committed.
