"""The `config`, `slot`, `step` and `rounds` command surface: parsers and rendering only; every decision is an operation's."""

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from ipaddress import ip_address
from pathlib import Path

from pydantic import ValidationError

from taskloop import cli_attempt, cli_composition, cli_land, dash_composition, operations, result_data, slot_list
from taskloop.agents.settings import Overrides
from taskloop.cli_common import (
    ARTIFACTS,
    DB,
    ConfigMissing,
    Parsers,
    add,
    backlog,
    backlog_of,
    checkout,
    checkout_of,
    common,
    group,
    label,
    label_of,
    tracker_root,
    tracker_root_of,
    views_for,
)
from taskloop.composition import real_slots
from taskloop.drain.models import Reason
from taskloop.exit_codes import exit_code
from taskloop.harness_choice import HarnessKind
from taskloop.machine_config import ConfigRefused, Effective, Flags, Loaded
from taskloop.new_task import NewTask
from taskloop.operations import Ended, Failed, Round, StartRequest
from taskloop.result_data import Result
from taskloop.round import NextRequest, run_round
from taskloop.rounds import RoundsRequest, run_rounds
from taskloop.slot_list_store import SlotListStore
from taskloop.step import Step, encode_step
from taskloop.step_guide import ROUNDS, STEP_ONLY
from taskloop.step_render import human
from taskloop.tracker import leaked_claim
from taskloop.workflow_read import DEFAULT

DASH_PORT = 8765
SCHEDULER, STEP, START = "rounds", "step", "start"
SLOTS = "slot"
COMMANDS = ("config", SLOTS, STEP, cli_attempt.GROUP, SCHEDULER, cli_land.GROUP)


def _binding(parser: argparse.ArgumentParser) -> None:
    """The three flags that bind a command to a tracker and a repository."""
    backlog(parser)
    tracker_root(parser)
    checkout(parser)


def _register_rounds(commands: Parsers) -> None:
    scheduler = group(commands, SCHEDULER, "Scheduling rounds over the whole backlog")
    _round_flags(
        add(
            scheduler,
            "once",
            "Run one scheduling round: settle existing attempts, advance claimed tasks whose "
            "step is done to the next step (no label check), start approved ready tasks in the free slots left, publish "
            "results accepted by factory commit, hold each task a round took that stopped "
            "(its label removed, `held` added, the claim "
            "returned, one comment: `bd list --label held`; adding the label back takes it again at plan) and remove "
            "`held` once a held task is taken again",
        )
    )
    rounds = add(scheduler, START, ROUNDS)
    rounds.add_argument(
        "--round-seconds",
        type=int,
        metavar="SECONDS",
        help="Seconds between regular rounds, at least 5 (overrides the machine config's round_seconds)",
    )
    rounds.add_argument(
        "--dash-host",
        type=ip_address,
        metavar="ADDRESS",
        default="127.0.0.1",
        help="Dashboard bind address: IPv4 or IPv6 literal (default 127.0.0.1)",
    )
    rounds.add_argument(
        "--dash-port",
        type=int,
        metavar="PORT",
        default=DASH_PORT,
        help=f"Serve the read-only dashboard on --dash-host:PORT while the rounds run (default {DASH_PORT}; 0 picks a free port)",
    )
    rounds.add_argument("--no-dashboard", action="store_true", help="Serve no dashboard (for a second rounds on one machine)")
    _round_flags(rounds)
    rounds.epilog = (
        "--json prints JSON Lines: one start record and one end record on a graceful stop; "
        "refusals and abrupt end results go to stderr. Dashboard notices go to stderr with --json."
    )


def register(commands: Parsers) -> None:
    config = group(commands, "config", "Machine configuration")
    show = add(config, "show", "Print each effective setting, its source, and the config file")
    common(show, DB, ARTIFACTS, "--slots-root")
    _harness_flag(show)
    show.add_argument("--slot-count", type=int, help="Slot count (overrides the machine config's slot_count)")
    slot = group(commands, SLOTS, "Managed slots: adopt them, list them")
    adopt = add(slot, "adopt", "Adopt worktrees made by hand with `git worktree add --detach <root>/<repo name>/sN`; creates factory.db")
    adopt.add_argument("checkout", metavar="CHECKOUT", help="The person's checkout of the repository")
    adopt.add_argument("--slot-count", type=int, help="Adopt s1..sN (overrides slot_count); adds slots only, retires none")
    common(adopt, "--slots-root", DB)
    common(
        add(
            slot,
            "list",
            "List the adopted slots from factory.db: name, path, repository id and whether a reservation holds it "
            "(free, or held with the holding attempt; read-only, no Git)",
        ),
        DB,
    )
    step = group(commands, STEP, f"Step attempts ({STEP_ONLY})")
    start = add(
        step,
        START,
        "Admit, relaunch or repeat the task's attempt (free slot, tracker claim), advance a done step, or "
        "re-run failed checks on the same commit. The tracker claim stays held between steps; nothing renews it then",
    )
    start.add_argument("task_id", metavar="TASK")
    _binding(start)
    start.add_argument("--minutes", type=int, required=True, help="Deadline of the attempt (or of its repeat), from now")
    _harness_flag(start)
    _new_task_flags(start)
    common(start, DB, ARTIFACTS)
    commit = add(
        step,
        "commit",
        "Complete factory commit: obtain the result commit and judge the step's rules, "
        "then release a clean slot and publish an accepted result; an agent step's only, never the checks",
    )
    commit.add_argument("task_id", metavar="TASK")
    backlog(commit)
    common(commit, DB, ARTIFACTS)
    release = add(step, "release", "Release the slot of a step that ended (parked where it was admitted, the claim kept)")
    abandon = add(
        step,
        "abandon",
        "Abandon the task's attempt: release the slot of any step whose entry and agent or checks are "
        "stopped, throw the attempt away and return the tracker claim (a land candidate's slot first, then the check "
        "step's, then its implement step's claim); `tl step start` then admits a fresh attempt",
    )
    for parser in (release, abandon):
        parser.add_argument("task_id", metavar="TASK")
        backlog(parser)
        common(parser, DB)
    publish = add(
        step,
        "publish",
        "Push the step's commit accepted by factory commit to origin's task/<id> as you, never forced; nothing merges or lands",
    )
    publish.add_argument("task_id", metavar="TASK")
    backlog(publish)
    common(publish, DB, ARTIFACTS)
    cli_attempt.register(commands)
    cli_land.register(commands)
    _register_rounds(commands)


def _harness_flag(parser: argparse.ArgumentParser) -> None:
    for flag in ("--model", "--effort"):
        parser.add_argument(flag, default=None, help="Override this field of each newly admitted step (flag > machine config > default)")
    parser.add_argument(
        "--harness",
        type=HarnessKind,
        choices=list(HarnessKind),
        default=None,
        help="Override each newly admitted step's configured harness",
    )


def _new_task_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--from",
        dest="start_step",
        type=Step,
        choices=[Step.IMPLEMENT],
        default=None,
        help="Start a new task at implement from the plan committed at its source commit (refused when none is valid), not at plan",
    )
    parser.add_argument(
        "--workflow",
        default=DEFAULT,
        metavar="NAME",
        help="Take a new task's prompts and agent choice from "
        ".task-loop/workflows/NAME.toml at its source commit; a task keeps the file it started with",
    )


def _round_flags(parser: argparse.ArgumentParser) -> None:
    _binding(parser)
    label(
        parser,
        "The tracker label approving a ready task for "
        "autonomous execution (`auto`), read only when a new task is taken; a claimed task advances without it",
    )
    parser.add_argument(
        "--max-running",
        type=int,
        default=3,
        metavar="N",
        help="Tasks of this backlog in flight (a step "
        "running, or passed and waiting to be landed, which counts until landed; not failed, stuck or held) "
        "at which no new task starts (default 3, at least 1); claimed work advances regardless. Start only what you "
        "approved: use a label only those tasks carry",
    )
    parser.add_argument("--minutes", type=int, required=True, help="Deadline of each attempt a round admits, from now")
    _harness_flag(parser)
    _new_task_flags(parser)
    parser.add_argument(
        "--retake-lapsed",
        action="store_true",
        help="After a factory.db discard only: also take the tasks "
        "`taskloop` still holds in progress with an expired lease and no attempt here (assumes this is the one "
        "factory on the tracker); run it once, with `tl rounds once`",
    )
    common(parser, DB, ARTIFACTS)


def _start(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    request = StartRequest(
        arguments.task_id,
        backlog_of(arguments, loaded),
        tracker_root_of(arguments, loaded),
        checkout_of(arguments, loaded),
        loaded.settings.agents,
        _overrides(arguments),
        arguments.minutes,
        new=_new_task(arguments),
    )
    with cli_composition.open_start(loaded.settings.db.value, loaded.settings.artifacts.value, views_for(loaded)) as ports:
        return ports if isinstance(ports, Failed) else operations.start(ports, request)


def _overrides(arguments: argparse.Namespace) -> Overrides:
    return Overrides(harness=arguments.harness, model=arguments.model, effort=arguments.effort)


def _new_task(arguments: argparse.Namespace) -> NewTask:
    return NewTask(start=arguments.start_step, workflow=arguments.workflow)


def _next_request(arguments: argparse.Namespace, loaded: Loaded) -> NextRequest:
    return NextRequest(
        backlog_of(arguments, loaded),
        tracker_root_of(arguments, loaded),
        checkout_of(arguments, loaded),
        label_of(arguments, loaded),
        loaded.settings.agents,
        _overrides(arguments),
        arguments.minutes,
        max_running=arguments.max_running,
        retake=arguments.retake_lapsed,
        new=_new_task(arguments),
    )


def _next(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    settings, request = loaded.settings, _next_request(arguments, loaded)
    with cli_composition.open_next(settings.db.value, settings.artifacts.value, views_for(loaded), request.tracker_root) as ports:
        return ports if isinstance(ports, Failed) else run_round(ports, request)


def _dash_request(arguments: argparse.Namespace, settings: Effective, round_request: NextRequest) -> dash_composition.DashRequest | None:
    if arguments.no_dashboard:
        return None
    return dash_composition.DashRequest(
        round_request.backlog,
        round_request.tracker_root,
        round_request.label,
        arguments.dash_host,
        arguments.dash_port,
        settings.db.value,
        settings.artifacts.value,
        round_request.checkout,
    )


def _dashboard_notice(address: tuple[str, int]) -> str:
    host, port = address
    literal = ip_address(host)
    authority = f"[{host}]" if literal.version == 6 else host
    notice = f"Dashboard: http://{authority}:{port}/ (read-only, unauthenticated)"
    if not literal.is_loopback:
        notice += "; non-loopback exposure is your explicit choice; use a proxy with sign-in"
    return notice


def _rounds(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    """The start line once the rounds are set up, then the rounds; a `KeyboardInterrupt` anywhere (the second Ctrl-C) is
    the abrupt stop, exit 130 (the operation writes its `rounds stopped abrupt` line once its rounds started)."""
    settings, round_request = loaded.settings, _next_request(arguments, loaded)
    request = RoundsRequest(round_request.backlog, loaded.settings.round_seconds.value)
    log = settings.artifacts.value / "rounds.log"
    try:
        with cli_composition.open_rounds(settings.db.value, settings.artifacts.value, views_for(loaded), round_request) as ports:
            if isinstance(ports, (Failed, Ended)):
                return ports
            label = round_request.label.strip()  # as `run_round` reads it
            data = result_data.rounds_data(request.backlog, request.every, str(log), label, arguments.max_running)
            started = (
                json.dumps(data)
                if arguments.json_output
                else f"Rounds for backlog {request.backlog} every {request.every} s, taking tasks labelled {label!r}"
                + (" (and its own lapsed claims)" if arguments.retake_lapsed else "")
                + f", none new while {arguments.max_running} or more tasks of this backlog are in flight (a step running, or "
                f"passed and waiting to be landed, by a round under the profile's `land: auto`, else by a person); log: {log}; "
                + ("stop with Ctrl-C" if ports.ctrl_c else "Ctrl-C is ignored here: stop with SIGTERM")
            )
            print(started, flush=True)
            with dash_composition.serving(_dash_request(arguments, settings, round_request), views_for(loaded)) as address:
                if isinstance(address, Failed):
                    print(f"Dashboard not started ({address.detail}); the rounds go on without it", file=sys.stderr, flush=True)
                elif address is not None:
                    print(_dashboard_notice(address), file=sys.stderr if arguments.json_output else sys.stdout, flush=True)
                return run_rounds(ports, request)
    except KeyboardInterrupt:
        return Ended(request.backlog, "abrupt")


def _commit(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    name = backlog_of(arguments, loaded)
    with cli_composition.open_commit(loaded.settings.db.value, views_for(loaded), loaded.settings.artifacts.value) as opened:
        return opened if isinstance(opened, Failed) else operations.commit_task(*opened, name, arguments.task_id)


def _release(arguments: argparse.Namespace, loaded: Loaded, *, abandon: bool = False) -> Result:
    name = backlog_of(arguments, loaded)
    with cli_composition.open_release(loaded.settings.db.value, views_for(loaded)) as opened:
        if isinstance(opened, Failed):
            return opened
        return operations.release_task(*opened, name, arguments.task_id, abandon=abandon)


def _abandon(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    return _release(arguments, loaded, abandon=True)


def _publish(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    name = backlog_of(arguments, loaded)
    with cli_composition.open_publish(loaded.settings.db.value, views_for(loaded), loaded.settings.artifacts.value) as opened:
        return opened if isinstance(opened, Failed) else operations.publish_task(*opened, name, arguments.task_id)


def _adopt(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    settings = loaded.settings
    return cli_composition.adopt(
        settings.db.value, Path(arguments.checkout), settings.slots_root.value, settings.slot_count.value, real_slots(views_for(loaded))
    )


def _configuration(arguments: argparse.Namespace, loaded: Loaded) -> Loaded | Failed:
    flags = Overrides(harness=arguments.harness, model=arguments.model, effort=arguments.effort)
    try:
        settings = loaded.settings.agents.overridden(flags)
    except ValueError as error:
        return Failed("refused", "choices", str(error))
    sources = dict(loaded.settings.agent_sources)
    for step in Step:
        for key in ("harness", "model", "effort"):
            if getattr(flags, key) is not None:
                sources[f"agents.{encode_step(step)}.{key}"] = "flag"
    return replace(loaded, settings=replace(loaded.settings, agents=settings, agent_sources=sources))


def _slots(_arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_reads(loaded.settings.db.value, loaded.settings.artifacts.value, views_for(loaded)) as reads:
        return reads if isinstance(reads, Failed) else slot_list.list_slots(SlotListStore(reads.store.connect, reads.store.begin))


OPERATIONS: dict[tuple[str, str], Callable[[argparse.Namespace, Loaded], Result]] = {
    ("config", "show"): _configuration,
    (SLOTS, "adopt"): _adopt,
    (SLOTS, "list"): _slots,
    (STEP, START): _start,
    (SCHEDULER, "once"): _next,
    (SCHEDULER, START): _rounds,
    (STEP, "commit"): _commit,
    (STEP, "release"): _release,
    (STEP, "publish"): _publish,
    (STEP, "abandon"): _abandon,
    **cli_attempt.OPERATIONS,
    **cli_land.OPERATIONS,
}


def refused(arguments: argparse.Namespace, refusal: ConfigRefused) -> int:
    """A command's own config refusal (a bad file, or a value neither flag nor file gives): to stderr, exit 1."""
    result = operations.refused_config(refusal)
    print(
        json.dumps(result_data.as_data(result))
        if arguments.json_output
        else "\n".join(human(f"tl {arguments.command} {arguments.operation}", result, None)),
        file=sys.stderr,
    )
    return exit_code(result)


def run(arguments: argparse.Namespace) -> int:
    """Resolve the machine config (every command refuses a bad one), run the one operation, render it."""
    flags = Flags(
        getattr(arguments, "db", None),
        getattr(arguments, "artifacts", None),
        getattr(arguments, "slots_root", None),
        getattr(arguments, "slot_count", None),
        getattr(arguments, "round_seconds", None),
    )
    loaded = cli_composition.load_config(arguments.config, flags)
    if isinstance(loaded, ConfigRefused):
        result: Result = operations.refused_config(loaded)
    else:
        try:
            result = OPERATIONS[arguments.command, arguments.operation](arguments, loaded)
        except ConfigMissing as missing:
            result = operations.refused_config(missing.refused)
        except ValidationError as error:
            result = Failed("refused", "choices", str(error))
    failed = isinstance(result, Failed) or (
        isinstance(result, Ended) and result.reason not in {"interrupted", Reason.DRAINED, Reason.DRAINING}
    )
    stream = sys.stderr if failed else sys.stdout
    if arguments.json_output:
        admission = (arguments.command, arguments.operation) == (STEP, START)  # the one command whose refusals carry slots
        print(json.dumps(result_data.as_json(result, admission=admission)), file=stream)
    else:
        if isinstance(result, Failed) and result.claim_leaked:
            print(leaked_claim(arguments.task_id), file=sys.stderr)
        db = None if isinstance(loaded, ConfigRefused) else loaded.settings.db.value
        lines = human(f"tl {arguments.command} {arguments.operation}", result, db)
        if isinstance(result, Round) and not result.logged and not isinstance(loaded, ConfigRefused):
            lines.append(f"Log: not written ({loaded.settings.artifacts.value / 'rounds.log'})")
        print("\n".join(lines), file=stream)
    return exit_code(result)
