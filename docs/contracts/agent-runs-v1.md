# agent-runs v1: how a worker launcher tells a dashboard what it runs

task-loop never reads another tool's internal files. A tool that launches workers (the delegate plugin, a script, a
future runner) and wants them on the dashboard writes records in this format; task-loop reads only these. Either side
can change everything else freely. This file is the whole contract.

## Where

`<config>/agent-runs/`, where `<config>` is `$XDG_CONFIG_HOME` or `~/.config` (macOS, Linux), `%APPDATA%` (Windows).

```
agent-runs/runs/<run id>.json        one per worker run
agent-runs/lanes/<producer>.json     one per producer: its lanes' limits right now (optional)
```

## Run record

```json
{"v": 1, "producer": "delegate", "id": "4f1c...", "kind": "claude-p",
 "parent_session": "80cca6b4-...", "cwd": "/repo/.slots/s2", "title": "stage 2: write the parser",
 "model": "sonnet", "lane": "CLAUDE_CREDIT", "status": "running",
 "started": 1792338617.5, "ended": null, "exit": null,
 "session": "4f1c...", "transcript": null}
```

| field | required | meaning |
|---|---|---|
| `v` | yes | `1`. A reader skips records with any other major version |
| `producer` | yes | who wrote it (`delegate`, `tl`, ...) |
| `id` | yes | unique run id; the file name without `.json` |
| `kind` | yes | `claude-p` (headless Claude), `codex`, `subagent`, `other` |
| `parent_session` | yes | `$CLAUDE_CODE_SESSION_ID` of the session that launched it (empty if unknown): how a run is tied to a task |
| `cwd` | yes | absolute folder it runs in |
| `started` | yes | Unix seconds |
| `status` | yes | `running`, `completed`, `failed` |
| `title` | no | one line: what it was asked to do |
| `model`, `lane` | no | free text for display |
| `ended`, `exit` | no | set when it ends |
| `session` | no | for `kind: claude-p`: its Claude session id, so the log is `~/.claude/projects/*/<session>.jsonl` |
| `thread` | no | for `kind: codex`: its Codex thread id |
| `transcript` | no | absolute path to a log file the reader can tail (JSON lines in Claude's or Codex's format), when neither id finds it |

## Lanes record (optional)

```json
{"v": 1, "producer": "delegate", "at": 1792338617.5,
 "lanes": [{"name": "OPENAI_SUBSCRIPTION", "out_until": null, "why": null,
            "usage": [{"window": "5h", "used_pct": 41, "resets_at": 1792344318},
                      {"window": "week", "used_pct": 6, "resets_at": 1792931118}]},
           {"name": "CLAUDE_CREDIT", "out_until": 1793484000, "why": "credit balance too low", "usage": []}]}
```

A reader shows a lanes record only when `at` is less than 6 hours old.

## Rules

- Writers write atomically (temporary file, then rename), update the same file when a run ends, and delete their own
  records older than 7 days.
- Readers never write, ignore fields they do not know, skip unreadable files and records of another major version,
  and work when the folder does not exist.
- A new optional field is a minor change and keeps `v: 1`; removing or changing a field's meaning is `v: 2`.
- Records hold no secrets and no prompt bodies beyond the one-line `title`.
