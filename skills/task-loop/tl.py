#!/usr/bin/env python3
"""tl.py: the task-loop helper. Python 3.8+, standard library only; macOS, Linux (also in Docker).

  tl.py actor                                   the --actor name this session uses for every bd call
  tl.py bd ARGS...                              run bd with this session's actor (in the current directory)
  tl.py register [DIR]                          add a repo to the dashboard (default: current directory)
  tl.py claim ID [--worktree DIR]               claim a bead, record it (bd provenance + local event)
  tl.py heartbeat ID                            keep the claim alive (run in a background loop)
  tl.py stage ID TEXT                           record what the task is doing now (shown on the dashboard)
  tl.py worker ID --kind K --ref R [--title T]  record a worker run (codex | claude-p | subagent | other)
  tl.py land ID --sha SHA [--worktree DIR]      record the landing (before close)
  tl.py land-lock [--repo DIR] [--wait-min N] -- CMD...
                                                run CMD under the repo's land lock (the engine's); exits with CMD's code, 75 on timeout
  tl.py close ID [--reason R]                   close the bead, record it
  tl.py block ID --why TEXT                     block the bead with a question, record it
  tl.py slot list|take|release|reset|setup ...  slots (see SKILL.md, Slots)
  tl.py slot hold S --why TEXT [--for MIN]      keep the loop and run-task off a slot (a person, screenshots)
  tl.py worktree start|sunset ...               one worktree per loop session when slots are off
  tl.py usage '<plan.windows JSON>'             feed get_usage to delegate (every 20 min while an engine runs)
  tl.py reflect digest [--since 24h] [--dry-run]  the last day's run reflections into one bead per recurring cause
  tl.py trace [ID] [--last N] [--json]          engine runs and every worker session of each (for reflection)
  tl.py run-task ID [--worktree DIR] [--slot S|any [--wait]] [--exclusive-area] [--dry-run] [--fresh]
                                                one bead through the engine (engine.py), no judgement here
  tl.py next [--repo DIR] [--json]              the bead the loop would take next and why (claims nothing)
  tl.py loop [--repo DIR] [--max-beads N] [--until HH:MM] [--wait-slot-min M] [--wait-drained] [--pin]
                                                run ready beads one after another, each in any free slot
  tl.py loop status [--repo DIR] [--last N]     the running loop and its last beads
  tl.py stop [--repo DIR] [--now]               stop the loop after its current bead, or now (SIGTERM)
  tl.py report [--repo DIR] [--since T] [--until T] [--json]
                                                 the M2 scorecard of a window (see SKILL.md, Report)
  tl.py lost [--repo DIR] [--since T] [--json]  bead-branch commits that are not landed, reclaimed or pending
  tl.py dash ensure|stop|status|url             the dashboard server (one per machine)
  tl.py pin [VERSION] [--delegate V] [--clear]  pin the plugin install a loop and run-task use (owner override; the loop never pins)
  tl.py rollback                                pin the previous task-loop version (the delegate stays as it is)
  tl.py cutover check [--json]                  live runs and loops on this machine; exit 1 if any (docs/cutover.md)
  tl.py hook session-start                      SessionStart hook: index session id -> transcript path

State: ~/.config/task-loop : repos.json, events.jsonl, sessions/, dash.*.
"""

import argparse
import sys
from pathlib import Path

import vendored  # noqa: F401  (puts _vendor on sys.path)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # taskloop: the typed records and adapters ship in the plugin dir
import dash_server  # noqa: E402
from taskloop.adapters import beadtools, gitrepo, ident, landlock
from taskloop.app.release import pins
from taskloop.app.track import trail, verbs
from taskloop.app.wire import asks as wire_asks
from taskloop.app.wire import doctor, hook as wire_hook
from taskloop.app.wire import slots as wslots
from taskloop.app.wire import usage as wire_usage
from taskloop.cli import asks as cli_asks
from taskloop.cli import slots as slots_cli

HERE = Path(__file__).resolve().parent


def cmd_slot(a, now=trail.now):
    return slots_cli.run(wslots.slot_env(gitrepo.repo_root(), now=now), a)


def cmd_ask(a):
    """The owner's inbox and typed verbs (answer, hint, hold, override) from the terminal: src/taskloop/cli/asks.py over the AskStore. A
    bead's ask names its repo, and the bd of that repo takes the bead's state."""
    if a.op == "list":
        for b in wire_asks.sweep("close"):  # throttled: the loop sweeps too
            print("closed the ask of %s: its bead is closed or gone" % b)
    return cli_asks.run(a, wire_asks.store(), lambda repo: beadtools.bd_store(repo or None), trail.now, ident.actor())


def cmd_land_lock(a):
    """Run a command while holding the repo's land lock (what the engine takes around fetch, rebase, gate, push)."""
    cmd = list(a.cmd_args)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("land-lock: no command (usage: tl.py land-lock [--repo DIR] -- CMD...)", file=sys.stderr)
        return 2
    return landlock.run_locked(cmd, str(Path(a.repo).resolve()), a.wait_min)


def cmd_reflect(a):
    import reflect_digest
    return reflect_digest.cmd_reflect(a)



def owner_parsers(sp):
    sp.add_parser("actor")
    sp.add_parser("selftest", help="run one bead through the engine with a fake lane in a temp repo; exit 1 when it cannot")
    sp.add_parser("doctor", help="warn about git settings that let a slot's git leave the slot")
    p = sp.add_parser("register", help="add a repository to the dashboard")
    p.add_argument("directory", nargs="?", default=".", metavar="DIR",
                   help="Git working directory (default: current directory)")
    p = sp.add_parser("bd")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p = sp.add_parser("claim")
    p.add_argument("id")
    p.add_argument("--worktree")
    p.add_argument("--slot")
    p = sp.add_parser("land")
    p.add_argument("id")
    p.add_argument("--sha", required=True)
    p.add_argument("--worktree")
    p = sp.add_parser("close")
    p.add_argument("id")
    p.add_argument("--reason")
    p = sp.add_parser("block")
    p.add_argument("id")
    p.add_argument("--why", required=True)
    p = sp.add_parser("slot")
    p.add_argument("op", choices=["list", "init", "take", "release", "reset", "setup", "hold"])
    p.add_argument("name", nargs="?")
    p.add_argument("--bead")
    p.add_argument("--n")
    p.add_argument("--force", action="store_true")
    p.add_argument("--why", help="hold: what the slot is held for (shown by tl slot list)")
    p.add_argument("--for", dest="for_min", type=float, help="hold: minutes until it expires (default 60); hold again to renew")
    p = sp.add_parser("worktree")
    p.add_argument("op", choices=["start", "sunset"])
    p.add_argument("--self-too", action="store_true")
    cli_asks.add_parsers(sp)
    p = sp.add_parser("dash")
    p.add_argument("op", choices=["ensure", "stop", "status", "url"])


def engine_parsers(sp):
    p = sp.add_parser("run-task")
    p.add_argument("id")
    p.add_argument("--worktree")
    p.add_argument("--slot", help="a slot name, or `any`: the next free slot in line (see --wait)")
    p.add_argument("--wait", action="store_true", help="--slot any: wait in line for a free slot instead of refusing")
    p.add_argument("--exclusive-area", action="store_true",
                   help="refuse (taken) when the bead's area has a bead running elsewhere; default: warn and run")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--fresh", action="store_true", help="drop the bead's checkpoint: plan again from the start")
    p.add_argument("--quiet", action="store_true", help="only steps and ⚠ lines (default: verbose, for a watching coordinator)")
    p.add_argument("--outcome-file", help="also write the outcome (the last stdout line, JSON) to this file")
    p = sp.add_parser("usage", help="pass get_usage's plan.windows (JSON) to delegate, so headless Claude steps may run")
    p.add_argument("windows")
    p = sp.add_parser("land-lock", help="run a command under the repo's land lock (the one the engine lands under)")
    p.add_argument("--repo", default=".", metavar="DIR", help="Git working directory (default: current directory)")
    p.add_argument("--wait-min", type=float, default=None, help="give up (exit 75) after this many minutes")
    p.add_argument("cmd_args", nargs=argparse.REMAINDER, metavar="-- CMD")
    p = sp.add_parser("trace", help="engine runs of a bead (or all) with every worker session and its transcript")
    p.add_argument("id", nargs="?", default="")
    p.add_argument("--last", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p = sp.add_parser("reflect", help="turn the last day's run reflections into beads, one per recurring cause (tl-bl5)")
    p.add_argument("op", choices=["digest"])
    p.add_argument("--since", help="window start: 24h (default), a time, or epoch seconds")
    p.add_argument("--until", help="window end (default now)")
    p.add_argument("--dry-run", action="store_true", help="file nothing, write no state")
    p.add_argument("--json", action="store_true")
    p = sp.add_parser("next", help="the bead the loop would take next and why (claims nothing)")
    p.add_argument("--repo")
    p.add_argument("--json", action="store_true")
    p = sp.add_parser("loop", help="run ready beads one after another, each in any free slot (see SKILL.md, Loop)")
    p.add_argument("op", nargs="?", choices=["run", "status"], default="run")
    p.add_argument("--repo")
    p.add_argument("--max-beads", type=int, default=0)
    p.add_argument("--until", metavar="HH:MM", help="start no bead after this local time")
    p.add_argument("--wait-slot-min", type=float, default=30, help="say so this often while no slot is free")
    p.add_argument("--wait-drained", action="store_true", help="no ready bead: poll every 5 min instead of ending")
    p.add_argument("--pin", action="store_true", help="stay on this install (default: between beads, move to the newest installed one)")
    p.add_argument("--last", type=int, default=10, help="status: how many finished beads to show")
    p = sp.add_parser("stop", help="stop the repo's loop after its current bead (--now: SIGTERM the bead's run)")
    p.add_argument("--repo")
    p.add_argument("--now", action="store_true")
    p = sp.add_parser("report", help="the M2 scorecard: landed, asks, parked, paused, failed, crashes, lost work")
    p.add_argument("--repo")
    p.add_argument("--since", metavar="T", help="ISO, HH:MM (today) or a duration back (12h); default 24h")
    p.add_argument("--until", metavar="T", help="as --since; default now")
    p.add_argument("--json", action="store_true")
    p.add_argument("--planner", action="store_true", help="only the planner table: calls and input tokens per bead")
    p.add_argument("--prefix", metavar="P[,P]", help="with --planner: only beads with these id prefixes (default all)")
    p = sp.add_parser("lost", help="task/* and wip/* commits not on the base: landed, reclaimed, pending or lost")
    p.add_argument("--repo")
    p.add_argument("--since", metavar="T")
    p.add_argument("--json", action="store_true")
    p = sp.add_parser("pin", help="pin the plugin install loops and runs use (owner override; --clear removes the pin)")
    p.add_argument("version", nargs="?", help="task-loop version (a cache dir under ~/.claude/plugins/cache)")
    p.add_argument("--delegate", metavar="V", help="delegate version")
    p.add_argument("--clear", action="store_true")
    sp.add_parser("rollback", help="pin the previous task-loop version")
    p = sp.add_parser("cutover", help="cutover check: live runs and loops; exit 1 if any (docs/cutover.md)")
    p.add_argument("op", choices=["check"])
    p.add_argument("--json", action="store_true")
    p = sp.add_parser("hook")
    p.add_argument("op", choices=["session-start"])


def build_parser():
    ap = argparse.ArgumentParser(prog="tl.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    owner_parsers(sp)
    engine_parsers(sp)
    return ap


def main(argv=None, here=HERE, now=trail.now):
    """`here`: the install this run executes from, `now`: the clock (a test runs the loop as another version, at another time)."""
    a = build_parser().parse_args(argv)

    if a.cmd == "run-task":
        import engine
        return engine.main(a)
    if a.cmd == "selftest":
        import selftest
        return selftest.cmd_selftest(a)
    if a.cmd == "cutover":
        import loop_env
        return loop_env.cmd_cutover(a)
    if a.cmd in ("next", "loop", "stop"):
        import loop_env
        a.argv = list(argv) if argv is not None else sys.argv[1:]  # the loop re-execs itself with these
        return {"next": loop_env.cmd_next, "loop": loop_env.cmd_loop, "stop": loop_env.cmd_stop}[a.cmd](a, here, now)
    if a.cmd in ("report", "lost"):
        import report
        return {"report": report.cmd_report, "lost": report.cmd_lost}[a.cmd](a)
    if a.cmd == "hook":
        wire_hook.session_start(sys.stdin.read())
        dash_server.restart_stale()
        return 0
    table = {"actor": lambda a: print(ident.actor()) or 0, "bd": lambda a: verbs.passthrough(a.rest),
             "register": lambda a: verbs.register(a.directory), "claim": lambda a: verbs.claim(a.id, a.worktree, a.slot),
             "land": lambda a: verbs.land(a.id, a.sha, a.worktree), "close": lambda a: verbs.close(a.id, a.reason),
             "block": lambda a: verbs.block(a.id, a.why), "trace": lambda a: verbs.trace(a.id, a.last, a.json),
             "usage": lambda a: wire_usage.feed(a.windows), "worktree": lambda a: wslots.worktree(a.op, a.self_too),
             "dash": lambda a: dash_server.run(a.op), "pin": lambda a: pins.run_pin(a.version, a.delegate, a.clear),
             "rollback": lambda a: pins.run_rollback(), "doctor": lambda a: doctor.run(), "slot": lambda a: cmd_slot(a, now), "ask": cmd_ask,
             "answer": cmd_ask, "hint": cmd_ask, "hold": cmd_ask, "override": cmd_ask, "reflect": cmd_reflect,
             "land-lock": cmd_land_lock}
    return table[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
