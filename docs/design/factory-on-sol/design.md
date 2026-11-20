# The factory on sol, driven from the phone

Status: **proposed**, revision 2 (2026-11-14), after Denis's answers: sol is a remote development box, not a
deployment. Plain scripts and tmux, no systemd units, installers or packaging. All Claude sessions in auto mode,
effort medium. Dashboard on the phone without a VPN. Nothing below is installed or started yet.

**Shape.** One `factory` script starts, stops, restarts and reports four things, each in its own tmux window:
the rounds (with the dashboard), two Remote Control sessions (task-loop supervisor, shelf) and a watch loop. The watch
is a small shell script with no Claude in it. It wakes the supervisor only when something changed. Denis reads,
decides and gets pushes in the Claude iOS app, and watches the dashboard in Safari through a password-protected proxy.
He never runs a command.

## 0. Verified facts this rests on (code.claude.com docs, 2026-11-14)

| Fact | Consequence |
|---|---|
| `claude remote-control` (alias `claude rc`) = server mode: `--name`, `--spawn worktree`, `--permission-mode`, `--settings FILE`, `--continue` (same session back for about 4 h after a stop). Exits after about 10 min without network. | Run it in a restart loop in tmux. |
| Needs a full claude.ai login. API keys and `claude setup-token` tokens are refused. First run in a directory asks for workspace trust on a TTY; trust is never saved for `$HOME`. | One interactive `claude auth login` and one first start per repo, in tmux (which has a TTY). |
| Pushes to iOS: `/config` "Push when Claude decides" and "Push when actions required"; questions and permission prompts wait until answered. | Decisions can wait for days. |
| `/loop` and cron tasks are session-scoped, expire after 7 days, no catch-up. Cloud routines see no local files. | The 10-min watch moves out of Claude. |
| Cross-session messages: an idle session starts a turn on a message; `$CLAUDE_CODE_MESSAGING_SOCKET` is given to hooks; a script may post to the socket; a message never counts as consent. | Supervisor and shelf talk directly; the watch can wake the supervisor. |

## 1. What lives where

Runs as Denis's own user on sol (a dev box; no separate user).

| Thing | Where |
|---|---|
| Owner checkout = tracker root (single `bd` writer from cut-over; the Mac stops writing) | `~/Workspaces/iorlas-task-loop` |
| Shelf checkout | `~/Workspaces/shelf` |
| Factory state, slots, config | the conventional paths (`~/.local/state/task-loop/`, `~/.local/share/task-loop/slots/iorlas-task-loop/s1..s6`, `~/.config/task-loop/config.toml` with `slot_count = 6`) |
| Factory code | today's way of running `tl` (Q11), never this checkout's working tree |
| Scripts | `~/Workspaces/iorlas-task-loop/scripts/factory` (Q13: or a dotfiles/homelab folder): `factory up`, `down`, `status`, `restart <part>`, `pause <minutes>` |
| Ops state | `~/.local/state/factory-ops/` (watch fingerprint, supervisor socket path, pause note, per-part pid files) |
| Secrets | Denis's normal `gh` login, Git push credential, `~/.codex/auth.json`, `~/.claude/.credentials.json`, the proxy's bcrypt hash; factory agents keep the scrubbed environment and push bar |
| Tracker backup | the watch runs `bd dolt push` hourly (Q5); the offsite copy is `refs/dolt/data` on GitHub |

**The tmux session `factory`:**

| Window | Runs | Kept alive by |
|---|---|---|
| `rounds` | `tl step rounds … --max-running 6` (dashboard on 127.0.0.1:8765) | a bash loop in the script: exit 0 (deliberate stop) ends it; a non-zero exit restarts after 60 s, at most 3 times in 30 min, then the window stays dead and the watch reports it |
| `supervisor` | `claude rc --name factory-supervisor --spawn worktree --permission-mode auto --settings <file> --continue` in the owner checkout | loop: always restart after 30 s |
| `shelf` | the same in the shelf checkout, `--name shelf` | the same |
| `watch` | `while true; do factory-watch; sleep 300; done` | the loop itself |

`factory up` is idempotent: it starts only the windows whose recorded pid is not alive (pid plus start time, never a
name match), so the supervisor can run it after any problem and Denis's "restart the factory" maps to it. `factory down`
sends SIGINT to the confirmed rounds pid (stop new work; running attempts go on, the drain rule) and never kills a tmux
window or server: closing a window would send SIGHUP to whatever still shares its terminal.

**What breaks without systemd, honestly:**

| Event | Effect | Smallest fix |
|---|---|---|
| Reboot of sol | Nothing runs, the watch included, so no alert. Denis sees the supervisor offline (grey dot) in the app. | One user crontab line `@reboot ~/…/scripts/factory up` (if sol has cron; Q-H2). Recommended: it is one line. Without it, someone runs `factory up` after a reboot. |
| tmux server crash or OOM kill | All windows gone, same as a reboot; running attempts may survive (they are not in tmux's terminal if the factory gives entries their own session; to test). | The watch cannot see its own death; the `@reboot` line does not help. Accepted: rare. |
| A process crash | The window's loop restarts it (rounds at most 3 times). | Built in. |
| Memory pressure from 6 agents | No cgroup limits; the kernel OOM killer picks a victim. | Start at `--max-running 2`, raise after a clean day; check sol's RAM (Q-H2). |

Clock: a box that does not sleep removes the Mac's +6 h jump, unless sol is a VM its host suspends (Q-H1). The watch
reports when NTP is not synced.

## 2. The watch and the sessions

**Watch (shell, no Claude, every 5 min).** Reads `tl step list --json`, the pid files, `curl 127.0.0.1:8765`,
`df`, `timedatectl`, `claude auth status`, `codex login status`, `gh auth status`; never `rounds.log` text. On a change
of the fingerprint (or at 08:00 for the digest) it posts one line to the supervisor's socket (path written by the
supervisor's `SessionStart` hook). When Claude itself is the problem (login gone, supervisor dead), it sends an
out-of-band push (Q12). **Spike first:** the socket's line format and whether a server-mode session binds it. Fallback:
the supervisor runs a `Monitor` on `~/.local/state/factory-ops/events` on every start and the watch appends there.

| | supervisor | shelf |
|---|---|---|
| Directory | owner checkout; code changes only in `--spawn worktree` sessions or worktree subagents | shelf checkout; a worktree per change |
| Mode, effort, model | auto, **medium**, Opus (Q9) | auto, **medium**, Opus (Q9) |
| Revive | the tmux loop with `--continue`; after more than about 4 h down it gets a new session and rebuilds its picture from `tl step list`, `bd` and the ops bead | the same |
| From iOS | Claude app → Code → `factory-supervisor` | Code → `shelf` |
| Does by itself | reads events; re-queues held tasks with a tracker comment; files beads; feeds tasks Denis dictates; `factory up`/`restart` with the reason as a comment on an ops bead; daily digest; pause/resume | shelf change in a worktree, PR through shelf's gate, PR link as a comment on the requesting bead, reply to the supervisor |
| Asks Denis | upgrades and rollbacks (owner pin), abandoning running work, discarding factory.db, config/label/land-mode changes, needs_owner answers, deleting anything | changes to a shelf API's behaviour |
| Never | kill by name, delete worktrees/slots/artifacts/old homes, force push, edit the owner checkout | merge, tag, force push (see Q4) |

**Shelf protocol.** The bead in the task-loop tracker is the record; a `SendMessage` naming the bead is the doorbell.
**Q4, honestly:** the classifier denies sessions merging PRs, tagging releases and force pushing, and auto mode is a
classifier, not a guarantee; an allow rule may not be honoured (not verified). So either GitHub does it (auto-merge on
a green gate plus a workflow that tags the squash merge commit from the version in `pyproject.toml`), or Denis taps
Merge on a link and the workflow tags. A session never merges or tags. The pin bump in task-loop (pyproject, `uv.lock`,
`tests/rules/test_isolation.py` SHARED) is made by a supervisor worktree session as a PR; factory agents cannot,
having no network.

## 3. The dashboard on the phone, without a VPN

The dashboard stays on 127.0.0.1:8765. What a viewer sees: task ids and titles, states and hold reasons, attempt
details including the agent's reasoning and last commands, check names and output paths, file paths under Denis's
home, branch names and commit ids. It has no write route.

| Option | Phone needs | Exposure | Auth strength | Moving parts | Verdict |
|---|---|---|---|---|---|
| **A. Reverse proxy (nginx or Caddy) with HTTPS and basic auth** | Safari, password from the password manager | one HTTPS port reachable from the internet (on sol or the homelab's edge) | one long random password (32+ chars, bcrypt hash in the config); brute force infeasible; nginx `limit_req` + fail2ban for noise and lockout (Caddy needs a plugin for rate limits) | proxy, domain, certificate (Let's Encrypt) | **recommended if the homelab already runs a proxy with a domain and TLS** |
| B. Cloudflare Tunnel + Access | Safari, email code or passkey | no open port; `cloudflared` runs outbound on sol | strong (Access login, Cloudflare rate limits) | Cloudflare account, domain on Cloudflare, a daemon; Cloudflare sees the traffic | recommended instead of A when sol has no inbound port and no proxy exists |
| C. SSH port forward from a phone app (Termius, Blink) | an SSH app in the foreground; iOS drops background tunnels | needs SSH reachable | key-based, strong | none on sol | clumsy, battery and foreground issues |
| D. Signed or token URL | a bookmark | the open port as in A | a secret in the URL: leaks via history, screenshots, logs; the dashboard has no code to check it | needs factory code | no |

Proxy rules for A: one hostname, only `GET` and `HEAD`, only the dashboard's paths, everything else 404; SSE needs
buffering off (`proxy_buffering off` in nginx; Caddy streams by default) and a long read timeout; access log kept for
fail2ban; no other upstream on that host name.

**If the password leaks:** the holder can read everything listed above, live, until the password is changed. They
cannot start, stop, land or change anything. Risks are the content itself (task text and agent output could quote a
secret if an agent printed one; agents run with a scrubbed environment, so this is unlikely, not impossible) and
load (many SSE connections; the rate limit caps it). Recommendation: no redaction now (it would be new factory code
for a read-only page of a dev box); rotate the password if it leaks; revisit if a repository with confidential task
text joins the factory (Q14).

## 4. Denis's day

**Status line** (reply to "status", head of every digest):

```
factory  running 3d4h · factory a1b2c3d · last round 20s ago
slots    4/6 busy · 2 waiting to land · 9 ready (auto)
held     3 — 1 waits for YOU since 09:12 (5h) · 2 being handled
landed   5 since 08:00 yesterday (links) · failed checks 1
health   disk 62% · clock synced · logins ok · shelf idle
next     nothing needs you  |  1 decision: tl-xyz
```

| Time | What he gets | What he does |
|---|---|---|
| 08:00 | Push "Overnight: 5 landed, 1 decision, healthy"; the status line and landed tasks with commit links | reads; optionally opens the dashboard |
| 09:12 | Push "Decision needed: tl-abc"; a question card with context, options and the recommended one | taps an option or types words; the supervisor comments it on the task and re-queues it |
| 03:10 | An approved schema upgrade fails to start: with Q7 = yes, push "Rolled back to the previous version, running since 03:24, 4 tasks restart at plan, bug tl-def filed"; otherwise a decision card and the factory stays stopped (stated as stopped, not quiet) | morning: "retry after the fix" or "stay" |
| 11:30 | "tl-ghi needs a shelf change; shelf PR #212 in its gate; tl-ghi held for it." Later: "tagged v0.18.0; pin bump PR merged; tl-ghi re-queued" | nothing, or taps Merge if Q4 = (b) |
| 14:05 | "Landed tl-jkl: squash on main (link), checks passed, no check config changed" | post-factum: "ok", silence, or "wrong because X" → a follow-up bead |
| 17:00 | He says "stop everything for an hour"; card: "Stop new work and let 3 running attempts finish (recommended), or also abandon them?" | taps; rounds get SIGINT, reason on the ops bead, the watch starts them at 18:00 from the pause note; status says "paused by you until 18:00" |

## 5. Failure modes

| Failure | Detects | Then | Denis hears |
|---|---|---|---|
| Reboot | `@reboot` line (if added), else nobody | `factory up`; intact factory.db continues; lost attempts abandoned with reason "reboot" | supervisor push after start; without the line: only the grey dot |
| rc session exits | its tmux loop | restart with `--continue` | nothing unless it is a new session |
| Rounds dies | its loop (3 tries), then the watch | supervisor reads the exit, fixes or files a bug, restarts with a reason | push if still down |
| claude login expires | watch | rc sessions fail; out-of-band push | "Claude login on sol expired; factory keeps running" |
| codex login expires | held tasks + watch | supervisor stops new work, asks | card with the sign-in link if the device flow works (not verified) |
| GitHub rate limit | holds with the cause | wait for reset, re-queue with a comment | only if over 1 h |
| Disk 80% / 90% | watch | report the largest folders; at 90% stop new work; delete nothing | decision card |
| Phone offline | — | work goes on; waits age in the status line | everything on return |
| Clock not synced / jump | watch | list affected attempts | push |

## 6. Migration from the Mac VM

1. Homelab answers (section 7); tools on sol: git, uv, Python 3.15, just, bd + dolt, codex, claude, gh, tmux; logins.
2. Test first with a scratch repo and tracker on sol: codex sandbox probe and Run S (Landlock on sol's kernel); the
   M1–M4 smokes; `factory up/down/status`; rc reachable from the phone and back after a kill; the watch waking the
   supervisor; a push arriving; the dashboard through the proxy (SSE live); a reboot with the `@reboot` line.
3. Clone task-loop and shelf, config, six slots from origin `main`, `tl slot adopt`. Do not start rounds.
4. Drain the Mac (SIGINT the confirmed rounds pid; wait; every `task/<id>` on origin); stop the Mac's watch cron.
5. Tracker: Mac `bd dolt push`, sol pull; compare exports; the Mac stops writing.
6. Sol: `tl step next --retake-lapsed` once, then `factory up` at `--max-running 2`. factory.db is new.
7. After 48 h clean: 6 slots. The Mac's old home stays untouched (s2 and s4 hold unsaved work) until Denis decides.

Rollback until step 6: just restart the Mac rounds. After step 6: `factory down`, push the tracker back, Mac
`--retake-lapsed`.

## 7. Questions

**Decided by Denis (2026-11-14):** Q1 own user; Q2 his own `gh` login; Q3 no systemd, scripts + tmux, `@reboot` line
only if wanted; Q6 dashboard through a password-protected proxy, no VPN; Q9 auto mode and effort medium for all
sessions.

**Still open for Denis:**

| # | Question | Recommended |
|---|---|---|
| Q3a | Add the one `@reboot factory up` cron line? | yes |
| Q4 | Shelf merge and tag: (a) GitHub auto-merge + tag workflow; (b) you tap Merge, workflow tags | (a) |
| Q5 | Hourly `bd dolt push` by the watch (also the offsite backup)? | yes |
| Q6a | Proxy A on the homelab's existing proxy, or Cloudflare Tunnel + Access (B)? | A if a proxy, domain and TLS exist; else B |
| Q7 | Roll back to the previous version automatically when an approved upgrade fails to start? | yes, and report |
| Q8 | Pin bump in task-loop: supervisor PR with auto-merge, or an `auto` factory task? | supervisor PR |
| Q9 | Model for the sessions | Opus |
| Q10 | New tasks from now: dictate to the supervisor? | yes |
| Q11 | How sol runs `tl`: the pinned install of branch `claude/factory-continuation` (not on `main`; `main`'s roadmap removed it), or a runner worktree's `.venv` (no installer, matches "no installers") | runner worktree until the pin design lands |
| Q12 | Out-of-band alerts when Claude is down: the homelab's alerting, ntfy, or none | the homelab's, else ntfy |
| Q13 | Where the `factory` scripts live: task-loop `scripts/`, or your dotfiles/homelab repo | task-loop `scripts/` |
| Q14 | Redact anything on the dashboard? | no, for now |

**For the "Linux VM host design" session (relay as is):**

1. Is sol bare metal or a VM? Can its host suspend it? Is NTP synced?
2. CPU, RAM, free disk, kernel version (Landlock), distro; is user cron available (for `@reboot`), and tmux?
3. Is there already a reverse proxy on sol or the homelab (nginx, Caddy, Traefik)? Which domain and how is TLS
   issued? Is any HTTPS port reachable from the internet, and through what (router forward, Cloudflare)?
4. Is the domain on Cloudflare? Is a Cloudflare Tunnel already used?
5. How are `claude rc` sessions kept running there today (tmux, screen, other)? Which user and directories?
6. Which secrets already live on sol (gh, SSH keys, claude login) and where?
7. Existing alerting (ntfy, Telegram, email) the watch can call?
8. Any egress proxy or `ANTHROPIC_BASE_URL` set (Remote Control refuses them)?
9. Are home directories backed up, how often, kept where?

**Not verified:** the watch-to-socket format and socket binding in server mode; proactive pushes from server-mode
sessions; allow rules under auto mode for merge/tag; headless `claude auth login` and `codex login --device-auth`;
whether launched attempts survive a tmux window's SIGHUP; SSE through Cloudflare's proxy timeouts; nginx bcrypt
support on sol's libc; Remote Control quota use of an always-on session.
