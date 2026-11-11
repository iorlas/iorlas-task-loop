"""The `config`, `slot` and `step` command surface: parsers and rendering only; every decision is an operation's."""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from taskloop import attempt_status, cli_composition, operations, result_data
from taskloop.exit_codes import exit_code
from taskloop.machine_config import ConfigRefused, Flags, Loaded
from taskloop.operations import Ended, Failed, Round, StartRequest
from taskloop.result_data import Result
from taskloop.round import NextRequest, advance
from taskloop.rounds import RoundsRequest, run_rounds
from taskloop.step_guide import HELD, ROUNDS, STEP_ONLY
from taskloop.step_render import human
from taskloop.tracker import leaked_claim

type Parsers = argparse._SubParsersAction[argparse.ArgumentParser]
COMMANDS = ("config", "slot", "step")


def _common(parser: argparse.ArgumentParser, *flags: str) -> None:
    helps = {
        "--db": ("PATH", "factory.db (overrides the machine config)"),
        "--artifacts": ("DIR", "Artifacts root (overrides the machine config)"),
        "--root": ("DIR", "Slots root (overrides the machine config's slots_root)"),
    }
    for flag in flags:
        parser.add_argument(flag, metavar=helps[flag][0], help=helps[flag][1])
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data; refusals are JSON on stderr")


def _add(parsers: Parsers, name: str, text: str) -> argparse.ArgumentParser:
    return parsers.add_parser(name, help=text, description=text, allow_abbrev=False)


def register(commands: Parsers) -> None:
    config = _add(commands, "config", "Machine configuration").add_subparsers(dest="operation", required=True)
    show = _add(config, "show", "Print each effective setting, its source, and the config file")
    _common(show, "--db", "--artifacts", "--root")
    show.add_argument("--count", type=int, help="Slot count (overrides the machine config's slot_count)")
    slot = _add(commands, "slot", "Managed slots (setup)").add_subparsers(dest="operation", required=True)
    adopt = _add(slot, "adopt", "Adopt worktrees made by hand with `git worktree add --detach <root>/<repo_id>/sN`; creates factory.db")
    adopt.add_argument("checkout", metavar="CHECKOUT", help="The person's checkout of the repository")
    adopt.add_argument("--count", type=int, help="Slots s1..sN (overrides the machine config's slot_count)")
    _common(adopt, "--root", "--db")
    step = _add(commands, "step", f"Step attempts ({STEP_ONLY})").add_subparsers(dest="operation", required=True)
    start = _add(step, "start", f"Admit, relaunch or repeat the task's attempt (free slot, tracker claim); {STEP_ONLY}. {HELD}")
    start.add_argument("task_id", metavar="TASK")
    for flag in ("--backlog", "--tracker-root", "--checkout", "--model", "--effort"):
        start.add_argument(flag, required=True)
    start.add_argument("--minutes", type=int, required=True, help="Deadline of the attempt (or of its repeat), from now")
    _common(start, "--db", "--artifacts")
    status = _add(step, "show", f"The task's attempt, its entry, result and next action (read-only; {STEP_ONLY})")
    status.add_argument("task_id", metavar="TASK")
    status.add_argument("--backlog", required=True)
    _common(status, "--db", "--artifacts")
    listing = _add(step, "list", f"Every task's current attempt with its next action (read-only; {STEP_ONLY})")
    listing.add_argument("--stuck", action="store_true", help="Only attempts whose next action is stuck:* or unknown")
    _common(listing, "--db")
    verify = _add(step, "verify", f"Commit the step's listed files and verify them, then release a clean slot and publish a verified "
                  f"result ({STEP_ONLY})")
    verify.add_argument("task_id", metavar="TASK")
    verify.add_argument("--backlog", required=True)
    _common(verify, "--db")
    release = _add(step, "release", "Release the slot of a step that ended (parked where it was admitted, the claim kept); with --abandon, "
                   f"of any step whose entry and agent are stopped, and return the tracker claim ({STEP_ONLY})")
    release.add_argument("task_id", metavar="TASK")
    release.add_argument("--backlog", required=True)
    release.add_argument("--abandon", action="store_true", help="Throw the attempt away and give the task back; `tl step start` "
                         "then admits a fresh attempt")
    _common(release, "--db")
    _round_flags(_add(step, "next", "Run one scheduling round: settle existing attempts, start approved ready tasks "
                      f"in free slots, publish verified results; {STEP_ONLY}. {HELD}"))
    rounds = _add(step, "rounds", ROUNDS)
    rounds.add_argument("--every", type=int, metavar="SECONDS", help="Seconds between regular rounds, at least 5 (overrides the "
                        "machine config's round_seconds)")
    _round_flags(rounds)
    publish = _add(step, "publish", "Push the step's verified commit to origin's task/<id> as you, never forced; nothing merges or lands")
    publish.add_argument("task_id", metavar="TASK")
    publish.add_argument("--backlog", required=True)
    _common(publish, "--db")


def _round_flags(parser: argparse.ArgumentParser) -> None:
    for flag in ("--backlog", "--tracker-root", "--checkout", "--model", "--effort"):
        parser.add_argument(flag, required=True)
    parser.add_argument("--label", required=True, help="The tracker label approving autonomous execution (`auto`)")
    parser.add_argument("--minutes", type=int, required=True, help="Deadline of each attempt a round admits, from now")
    _common(parser, "--db", "--artifacts")


def _start(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    request = StartRequest(arguments.task_id, arguments.backlog, arguments.tracker_root, Path(arguments.checkout), arguments.model,
                           arguments.effort, arguments.minutes)
    with cli_composition.open_start(loaded.settings.db.value, loaded.settings.artifacts.value) as ports:
        return ports if isinstance(ports, Failed) else operations.start(ports, request)


def _next_request(arguments: argparse.Namespace) -> NextRequest:
    return NextRequest(arguments.backlog, arguments.tracker_root, Path(arguments.checkout), arguments.label, arguments.model,
                       arguments.effort, arguments.minutes)


def _next(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_next(loaded.settings.db.value, loaded.settings.artifacts.value, arguments.tracker_root) as ports:
        return ports if isinstance(ports, Failed) else advance(ports, _next_request(arguments))


def _rounds(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    """The start line once the rounds are set up, then the rounds; a `KeyboardInterrupt` anywhere (the second Ctrl-C) is
    the abrupt stop, exit 130 (the operation writes its `rounds stopped abrupt` line once its rounds started)."""
    settings, request = loaded.settings, RoundsRequest(arguments.backlog, loaded.settings.round_seconds.value)
    log = settings.artifacts.value / "rounds.log"
    try:
        with cli_composition.open_rounds(settings.db.value, settings.artifacts.value, _next_request(arguments)) as ports:
            if isinstance(ports, Failed):
                return ports
            started = (json.dumps(result_data.rounds_data(request.backlog, request.every, str(log))) if arguments.json_output else
                       f"Rounds for backlog {request.backlog} every {request.every} s; log: {log}; stop with Ctrl-C")
            print(started, flush=True)
            return run_rounds(ports, request)
    except KeyboardInterrupt:
        return Ended(request.backlog, "abrupt")


def _show(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_reads(loaded.settings.db.value) as reads:
        if isinstance(reads, Failed):
            return reads
        return attempt_status.show_attempt(reads, loaded.settings.artifacts.value, arguments.backlog, arguments.task_id)


def _list(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_reads(loaded.settings.db.value) as reads:
        return reads if isinstance(reads, Failed) else attempt_status.list_attempts(reads, stuck=arguments.stuck)


def _verify(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_verify(loaded.settings.db.value) as opened:
        return opened if isinstance(opened, Failed) else operations.verify_task(*opened, arguments.backlog, arguments.task_id)


def _release(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_release(loaded.settings.db.value) as opened:
        if isinstance(opened, Failed):
            return opened
        return operations.release_task(*opened, arguments.backlog, arguments.task_id, abandon=arguments.abandon)


def _publish(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_publish(loaded.settings.db.value) as opened:
        return opened if isinstance(opened, Failed) else operations.publish_task(*opened, arguments.backlog, arguments.task_id)


def _adopt(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    settings = loaded.settings
    return cli_composition.adopt(settings.db.value, Path(arguments.checkout), settings.slots_root.value, settings.slot_count.value)


OPERATIONS: dict[tuple[str, str], Callable[[argparse.Namespace, Loaded], Result]] = {
    ("config", "show"): lambda _arguments, loaded: loaded,
    ("slot", "adopt"): _adopt,
    ("step", "start"): _start,
    ("step", "next"): _next,
    ("step", "rounds"): _rounds,
    ("step", "show"): _show,
    ("step", "list"): _list,
    ("step", "verify"): _verify,
    ("step", "release"): _release,
    ("step", "publish"): _publish,
}


def run(arguments: argparse.Namespace) -> int:
    """Resolve the machine config (every command refuses a bad one), run the one operation, render it."""
    flags = Flags(getattr(arguments, "db", None), getattr(arguments, "artifacts", None), getattr(arguments, "root", None),
                  getattr(arguments, "count", None), getattr(arguments, "every", None))
    loaded = cli_composition.load_config(arguments.config, flags)
    if isinstance(loaded, ConfigRefused):
        result: Result = operations.refused_config(loaded)
    else:
        result = OPERATIONS[arguments.command, arguments.operation](arguments, loaded)
    failed = isinstance(result, Failed) or (isinstance(result, Ended) and result.reason != "interrupted")
    stream = sys.stderr if failed else sys.stdout
    if arguments.json_output:
        admission = (arguments.command, arguments.operation) == ("step", "start")  # the one command whose refusals carry slots
        print(json.dumps(result_data.as_data(result, admission=admission)), file=stream)
    else:
        if isinstance(result, Failed) and result.claim_leaked:
            print(leaked_claim(arguments.task_id), file=sys.stderr)
        db = None if isinstance(loaded, ConfigRefused) else loaded.settings.db.value
        lines = human(f"tl {arguments.command} {arguments.operation}", result, db)
        if isinstance(result, Round) and not result.logged and not isinstance(loaded, ConfigRefused):
            lines.append(f"Log: not written ({loaded.settings.artifacts.value / 'rounds.log'})")
        print("\n".join(lines), file=stream)
    return exit_code(result)
