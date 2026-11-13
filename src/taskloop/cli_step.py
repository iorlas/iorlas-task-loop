"""The `config`, `slot` and `step` command surface: parsers and rendering only; every decision is an operation's."""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from taskloop import attempt_status, cli_composition, dash_composition, land, operations, result_data
from taskloop.composition import real_slots
from taskloop.exit_codes import exit_code
from taskloop.git_views import GitViews
from taskloop.land_guide import INTERRUPTED
from taskloop.machine_config import ConfigRefused, Effective, Flags, Loaded
from taskloop.operations import Ended, Failed, Round, StartRequest
from taskloop.result_data import Result
from taskloop.round import NextRequest, run_round
from taskloop.rounds import RoundsRequest, run_rounds
from taskloop.step_guide import ROUNDS, STEP_ONLY
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
    adopt.add_argument("--count", type=int, help="Adopt s1..sN (overrides slot_count); adds slots only, retires none")
    _common(adopt, "--root", "--db")
    step = _add(commands, "step", f"Step attempts ({STEP_ONLY})").add_subparsers(dest="operation", required=True)
    start = _add(step, "start", "Admit, relaunch or repeat the task's attempt (free slot, tracker claim), advance a done step, or "
                 "re-run failed checks on the same commit. The tracker claim stays held between steps; nothing renews it then")
    start.add_argument("task_id", metavar="TASK")
    for flag in ("--backlog", "--tracker-root", "--checkout", "--model", "--effort"):
        start.add_argument(flag, required=True)
    start.add_argument("--minutes", type=int, required=True, help="Deadline of the attempt (or of its repeat), from now")
    _common(start, "--db", "--artifacts")
    status = _add(step, "show", "The task's attempt, its entry, setup run, result and next action (read-only)")
    status.add_argument("task_id", metavar="TASK")
    status.add_argument("--backlog", metavar="KEY", help="Task scope; defaults to the machine config's backlog, then the sole backlog "
                        "in factory.db")
    _common(status, "--db", "--artifacts")
    listing = _add(step, "list", "Every task's current attempt with its next action (read-only)")
    listing.add_argument("--stuck", action="store_true", help="Only attempts whose next action is stuck:*, hold or unknown")
    _common(listing, "--db")
    verify = _add(step, "verify", "Commit the step's listed files and verify them, then release a clean slot and publish a verified "
                  "result; an agent step's only, never the checks")
    verify.add_argument("task_id", metavar="TASK")
    verify.add_argument("--backlog", required=True)
    _common(verify, "--db")
    release = _add(step, "release", "Release the slot of a step that ended (parked where it was admitted, the claim kept); with --abandon, "
                   "of any step whose entry and agent or checks are stopped, and return the tracker claim (a land candidate's slot "
                   "first, then the check step's, then its implement step's claim)")
    release.add_argument("task_id", metavar="TASK")
    release.add_argument("--backlog", required=True)
    release.add_argument("--abandon", action="store_true", help="Throw the attempt away and give the task back; `tl step start` "
                         "then admits a fresh attempt")
    _common(release, "--db")
    _round_flags(_add(step, "next", "Run one scheduling round: settle existing attempts, advance claimed tasks whose "
                      "step is done to the next step (no label check), start approved ready tasks in the free slots left, publish "
                      "verified results, hold each task a round took that stopped (its label removed, `held` added, the claim "
                      "returned, one comment: `bd list --label held`; adding the label back takes it again at plan) and remove "
                      "`held` once a held task is taken again"))
    rounds = _add(step, "rounds", ROUNDS)
    rounds.add_argument("--every", type=int, metavar="SECONDS", help="Seconds between regular rounds, at least 5 (overrides the "
                        "machine config's round_seconds)")
    rounds.add_argument("--dash-port", type=int, metavar="PORT", help="Serve the read-only dashboard on 127.0.0.1:PORT while the "
                        "rounds run (0 picks a free port); without it nothing is served")
    _round_flags(rounds)
    rounds.epilog = ("--json prints JSON Lines: one start record and one end record on a graceful stop; "
                     "refusals and abrupt end results go to stderr. Dashboard notices go to stderr with --json.")
    publish = _add(step, "publish", "Push the step's verified commit to origin's task/<id> as you, never forced; nothing merges or lands")
    publish.add_argument("task_id", metavar="TASK")
    publish.add_argument("--backlog", required=True)
    _common(publish, "--db")
    _land_flags(_add(step, "land", LAND))


LAND = ("Land the task's checked commit X yourself: fetch origin's main (O), squash X onto it as one commit S (Git objects only), "
        "run every check again on S in a free slot, in this shell, only when main moved or its required names changed, push S "
        "to origin's main as you (never forced), then close the task in your local tracker (never synced: `bd dolt push` is "
        "yours). A rerun does only what is missing; under the profile's `land: auto` a round runs this same land by itself. "
        "Your checkout and local main are never written. Exit 0 landed "
        "(or already), 1 refused, 3 unknown (a rerun is safe), 130 interrupted by Ctrl-C (a rerun reconciles it)")


def _land_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("task_id", metavar="TASK")
    parser.add_argument("--backlog", required=True)
    parser.add_argument("--checkout", required=True, help="Your checkout of the repository: its origin is fetched and pushed")
    parser.add_argument("--minutes", type=int, help="Deadline of the validation of S, from now; needed when S must be validated (main "
                        "moved or its required names changed) or a pending candidate resumes; not for --summary, --withdraw, "
                        "--no-change or a same-tree land")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--summary", action="store_true", help="Print the land summary (the facts to read before landing); "
                      "records, reserves, pushes and closes nothing")
    mode.add_argument("--withdraw", action="store_true", help="Give up a validated, undelivered candidate (origin read "
                      "first, nothing pushed) so the task can be abandoned")
    parser.add_argument("--no-change", action="store_true", help="Accept that origin's main already holds X's changes: "
                        "recorded and closed with no push")
    parser.add_argument("--accept-gate-changes", action="store_true", help="Accept that S changes what decides a pass (a check's "
                        "argv, timeout, setup or required names, a configuration file, a weakened test): without it the land "
                        "refuses and lists them")
    _common(parser, "--db", "--artifacts")


def _round_flags(parser: argparse.ArgumentParser) -> None:
    for flag in ("--backlog", "--tracker-root", "--checkout", "--model", "--effort"):
        parser.add_argument(flag, required=True)
    parser.add_argument("--label", required=True, help="The tracker label approving a ready task for "
                        "autonomous execution (`auto`), read only when a new task is taken; a claimed task advances without it")
    parser.add_argument("--max-running", type=int, default=3, metavar="N", help="Tasks of this backlog in flight (a step "
                        "running, or passed and waiting to be landed, which counts until landed; not failed, stuck or held) "
                        "at which no new task starts (default 3, at least 1); claimed work advances regardless. Start only what you "
                        "approved: use a label only those tasks carry")
    parser.add_argument("--minutes", type=int, required=True, help="Deadline of each attempt a round admits, from now")
    parser.add_argument("--retake-lapsed", action="store_true", help="After a factory.db discard only: also take the tasks "
                        "`taskloop` still holds in progress with an expired lease and no attempt here (assumes this is the one "
                        "factory on the tracker); run it once, with `tl step next`")
    _common(parser, "--db", "--artifacts")


def views_for(loaded: Loaded) -> GitViews:
    """The real Git views, bounded by the machine config's `git_read_seconds`."""
    return GitViews(loaded.settings.git_read_seconds.value)


def _start(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    request = StartRequest(arguments.task_id, arguments.backlog, arguments.tracker_root, Path(arguments.checkout), arguments.model,
                           arguments.effort, arguments.minutes)
    with cli_composition.open_start(loaded.settings.db.value, loaded.settings.artifacts.value, views_for(loaded)) as ports:
        return ports if isinstance(ports, Failed) else operations.start(ports, request)


def _next_request(arguments: argparse.Namespace) -> NextRequest:
    return NextRequest(arguments.backlog, arguments.tracker_root, Path(arguments.checkout), arguments.label, arguments.model,
                       arguments.effort, arguments.minutes, max_running=arguments.max_running, retake=arguments.retake_lapsed)


def _next(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    settings = loaded.settings
    with cli_composition.open_next(settings.db.value, settings.artifacts.value, views_for(loaded), arguments.tracker_root) as ports:
        return ports if isinstance(ports, Failed) else run_round(ports, _next_request(arguments))


def _dash_request(arguments: argparse.Namespace, settings: Effective) -> dash_composition.DashRequest | None:
    if arguments.dash_port is None:
        return None
    return dash_composition.DashRequest(arguments.backlog, arguments.tracker_root, arguments.label, arguments.dash_port,
                                        settings.db.value, settings.artifacts.value, Path(arguments.checkout))


def _rounds(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    """The start line once the rounds are set up, then the rounds; a `KeyboardInterrupt` anywhere (the second Ctrl-C) is
    the abrupt stop, exit 130 (the operation writes its `rounds stopped abrupt` line once its rounds started)."""
    settings, request = loaded.settings, RoundsRequest(arguments.backlog, loaded.settings.round_seconds.value)
    log = settings.artifacts.value / "rounds.log"
    try:
        with cli_composition.open_rounds(settings.db.value, settings.artifacts.value, views_for(loaded), _next_request(arguments)) as ports:
            if isinstance(ports, Failed):
                return ports
            label = arguments.label.strip()  # as `run_round` reads it
            data = result_data.rounds_data(request.backlog, request.every, str(log), label, arguments.max_running)
            started = (json.dumps(data) if arguments.json_output else
                       f"Rounds for backlog {request.backlog} every {request.every} s, taking tasks labelled {label!r}"
                       + (" (and its own lapsed claims)" if arguments.retake_lapsed else "")
                       + f", none new while {arguments.max_running} or more tasks of this backlog are in flight (a step running, or "
                       f"passed and waiting to be landed, by a round under the profile's `land: auto`, else by a person); log: {log}; "
                       + ("stop with Ctrl-C" if ports.ctrl_c else "Ctrl-C is ignored here: stop with SIGTERM"))
            print(started, flush=True)
            with dash_composition.serving(_dash_request(arguments, settings), views_for(loaded)) as address:
                if isinstance(address, Failed):
                    print(f"Dashboard not started ({address.detail}); the rounds go on without it", file=sys.stderr, flush=True)
                elif address is not None:
                    print(f"Dashboard: http://{address[0]}:{address[1]}/",
                          file=sys.stderr if arguments.json_output else sys.stdout, flush=True)
                return run_rounds(ports, request)
    except KeyboardInterrupt:
        return Ended(request.backlog, "abrupt")


def _show(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_reads(loaded.settings.db.value, loaded.settings.artifacts.value, views_for(loaded)) as reads:
        if isinstance(reads, Failed):
            return reads
        return attempt_status.show_attempt(reads, loaded.settings.artifacts.value, arguments.backlog, arguments.task_id,
                                           configured_backlog=loaded.settings.backlog.value)


def _list(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_reads(loaded.settings.db.value, loaded.settings.artifacts.value, views_for(loaded)) as reads:
        return reads if isinstance(reads, Failed) else attempt_status.list_attempts(reads, stuck=arguments.stuck)


def _verify(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_verify(loaded.settings.db.value, views_for(loaded)) as opened:
        return opened if isinstance(opened, Failed) else operations.verify_task(*opened, arguments.backlog, arguments.task_id)


def _release(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_release(loaded.settings.db.value, views_for(loaded)) as opened:
        if isinstance(opened, Failed):
            return opened
        return operations.release_task(*opened, arguments.backlog, arguments.task_id, abandon=arguments.abandon)


def _publish(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_publish(loaded.settings.db.value, views_for(loaded)) as opened:
        return opened if isinstance(opened, Failed) else operations.publish_task(*opened, arguments.backlog, arguments.task_id)


def _land(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    """The one land; a `KeyboardInterrupt` (Ctrl-C) anywhere in it is `unavailable:interrupted`, exit 130: the land's own
    unwinding already stopped a running check's tree, and the rerun reconciles what is left (as the rounds' abrupt stop)."""
    mode: Literal["land", "summary", "withdraw"] = "summary" if arguments.summary else "withdraw" if arguments.withdraw else "land"
    request = land.LandRequest(arguments.backlog, arguments.task_id, Path(arguments.checkout), arguments.minutes, mode,
                               arguments.no_change, arguments.accept_gate_changes)
    try:
        with cli_composition.open_land(loaded.settings.db.value, loaded.settings.artifacts.value, views_for(loaded)) as ports:
            return ports if isinstance(ports, Failed) else land.land(ports, request)
    except KeyboardInterrupt:
        return Failed("unavailable", INTERRUPTED)


def _adopt(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    settings = loaded.settings
    return cli_composition.adopt(settings.db.value, Path(arguments.checkout), settings.slots_root.value, settings.slot_count.value,
                                 real_slots(views_for(loaded)))


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
    ("step", "land"): _land,
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
