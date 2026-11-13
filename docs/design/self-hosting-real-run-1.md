# Self-hosting real run 1: the factory on a real bead, the owner watching

Status: **evidence**. Dated self-hosting trial results and findings, not a current setup runbook.
Historical commands and environment details are preserved; current commands are in the [README](../../README.md).

Run 2026-11-12 on the owner's PC (Linux, OrbStack), `main` at `fe403175e` (PR #754). Codex 0.167.0, model `gpt-6.1-sol`,
effort `ultra`. Vocabulary: [glossary](../glossary.md). Follows [trial 6](self-hosting-trial-6.md). Tracker epic
`tl-8bh9.14`.

## 1. Setup

- Home `~/factory-successor`: own `config.toml`, `state/factory.db`, `state/artifacts`, `slots` (two adopted), and a
  clone `repo` of `git@github.com:iorlas/iorlas-task-loop.git` (a land pushes to the real `main`).
- **Tracker:** `--tracker-root /home/iorlas/Workspaces/iorlas-task-loop` (the owner's real embedded beads database, used
  only through `bd`, no file in that checkout touched, no `bd init`). Claims and comments there are real.
- Task `tl-8bh9.14.13`, label `real-run-1`. Twelve other ready beads carry `auto`, so `--label auto` would have started
  them all; the run used its own label (tl-8bh9.14.76).
- `tl step rounds --dash-port 8765 --label real-run-1 --minutes 90`, under `nohup`; dashboard on 127.0.0.1:8765.
  No screenshot was sent: the session had no browser.
- The owner's installed `tl` and `~/.config/task-loop` were not used.

## 2. The run

| Time (UTC) | Event |
|---|---|
| 21:34:13 | plan started (slot s1) |
| 21:38:21 | implement started (plan took about 4 min) |
| 21:48:16 | checks started (implement about 10 min) |
| 21:49:37 | checks passed, `report land` (about 1.5 min) |
| after | `tl step land --summary`: no gate change, no test weakening, 8 files +552 -60; held for the owner |
| later | owner said land; `tl step land` pushed `7df44b24a` to origin `main` (same tree as the checked commit, no re-check) and closed the bead in the local tracker (not synced with `bd dolt push`) |

## 3. Findings (beads under `tl-8bh9.14`)

| Bead | What |
|---|---|
| tl-8bh9.14.69 | No harness, version, thread id, model, effort or license lane per attempt; store them in factory.db, resolve the transcript path through a reader (Codex rollouts are `~/.codex/sessions/<date>/rollout-<time>-<thread>.jsonl`). |
| tl-8bh9.14.70 | "Quiet for N minutes" comes from the last-command file only; the agent thought and ran commands (no gap over 91 s in `events.jsonl`) yet showed quiet. Needs an explicit attempt state. |
| tl-8bh9.14.71 | Task drawer waits for three `bd` calls: 0.7-0.9 s idle, 3-8 s at load average 22 (the load, not `bd` startup, was the cause). Files are fast (5 ms). Open the drawer from factory.db, load tracker fields second. PoC on a scratch tracker: `bd show` 115-135 ms embedded, 77 ms in server mode (`bd init --server`); the real tracker was left embedded (owner decision). |
| tl-8bh9.14.72 | The "Land" column says the land is delivering; the task is waiting for the person. |
| tl-8bh9.14.73 | The squash commit title is cut mid-word (`...then the dashb`). |
| tl-8bh9.14.74 | "Attempt 2" reads as a retry; steps and tries are mixed. Steps top to bottom with idle gaps. |
| tl-8bh9.14.75 | Lines tab: jumps back on each new line, constant count, banner too loud, no thinking text, no gaps. |
| tl-8bh9.14.76 | A backlog with many `auto` beads starts all of them. |

Other points: every step's prompt starts with the bead's title, description and acceptance (`input.txt`), so that text
repeats by design. Transcripts should later be mined for repeated waste (long paths, repeated reads).

## 4. Not covered

Hold and conflict paths, a second task, the dashboard on a second device.
