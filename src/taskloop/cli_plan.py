"""The `config`, `slot` and `plan` command surface: parsers and rendering only; every decision is an operation's."""

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from taskloop import cli_composition, plan_data, plan_ops
from taskloop.machine_config import ConfigRefused, Flags, Loaded
from taskloop.plan import succeeded
from taskloop.plan_ops import (
    UNCLAIMING,
    Adoption,
    AttemptStatus,
    Checked,
    Failed,
    Freed,
    Listed,
    PublishedTask,
    Result,
    Shown,
    Started,
    StartRequest,
)
from taskloop.plan_publish import BranchPublished
from taskloop.plan_release import Released
from taskloop.plan_types import ATTEMPTS
from taskloop.slots import Adopted

type Parsers = argparse._SubParsersAction[argparse.ArgumentParser]
PLAN_ONLY = "plan step only: publishes task/<id>; no merge or land"
PUBLISH = ("The plan is verified but not on `origin` yet: `tl plan publish`. A `refused` word names what to fix; "
           "`unavailable:remote` is often credentials: check that `git push` works from this shell.")
COMMANDS = ("config", "slot", "plan")
HELD = ("The tracker claim stays held, and the slot until the step ends on a clean slot (`tl plan release` frees a slot left "
        "held; `--abandon` also returns the claim). While a step runs its entry renews the claim's bd lease every 100 s; between "
        "steps nothing does, so a `bd reclaim` run on that tracker can revert the claim once its lease lapses: at the earliest "
        "about 5 minutes after a step ends (bd's default reclaim grace is 10 minutes, so about 15 minutes with a plain `bd reclaim`).")
ABANDON = "`tl plan release --abandon` frees the slot and gives the task back."
GUIDE = {
    "start": "Re-run `tl plan start` to relaunch its entry. If the last entry says `claim_lost`, the tracker claim was taken "
    "back: check `bd show <task>`; re-claim it by hand as `taskloop` before `tl plan start`, or leave it.",
    "wait": "Its entry runs; wait, then `tl plan show` again.",
    "verify": "Run `tl plan verify`.",
    "repeat": "Run `tl plan start` again to repeat it with this listing as feedback, or remove the files and `tl plan verify`.",
    "repeats_exhausted": "Repeated twice and still unsettled: inspect the slot, tidy it, then `tl plan verify` (which releases "
    "the slot), or `tl plan release --abandon`.",
    "release": "The step ended; its slot is still held. Remove the listed files if any, then `tl plan release`; `--abandon` also "
    "gives the task back.",
    "abandoned": "Abandoned: the slot is free and the claim was returned (`Claim:` says if not). `tl plan start` admits a fresh "
    "attempt.",
    "publish": PUBLISH,
    "done": "Collected: `succeeded` tells whether the plan was verified.",
    "unknown": "The entry or the store could not be read; run `tl plan show` again.",
    "stuck:expired_admitted": f"Nothing ran. {ABANDON}",
    "stuck:entry_lost": "The agent may still run: if `Worker` names a pid, check its cwd is the slot (`lsof -a -p <pid> -d cwd`) "
    f"and stop only its group (`kill -TERM -<pgid>`); then {ABANDON} With no `Worker` recorded it cannot be shown stopped: "
    "only the whole-DB discard remains.",
    "stuck:hung": "Stop the worker first, the agent may keep editing the slot: check the `Worker` pid's cwd is the slot "
    "(`lsof -a -p <pid> -d cwd`), then `kill -TERM -<pgid>`. Then the entry: `ps -o command= -p <entry pid>` must show "
    f"taskloop.attempt_entry, then `kill -TERM <entry pid>`. Then {ABANDON}",
    "stuck:unpublished": f"The result is incomplete; keep the evidence. {ABANDON}",
    "stuck:conflict": f"The owner inspects the evidence; then {ABANDON}",
    "unsettled": "The slot has files the stage did not commit (listed), or the slot pointer or HEAD changed. Remove the "
    "listed files and `tl plan verify`, or run `tl plan start` again to repeat the step; for `redirected` or `head_moved` "
    "inspect first; for `worker_alive` stop the worker first; for `staged` unstage the listed paths first.",
    "registration_conflict": "Another start registered its entry first; `tl plan show` follows that attempt.",
    "slot_busy": "Another entry or verify holds the slot: wait and run it again; if nothing ends, see the `stuck:hung` guide.",
    "lock": "The slot's lock file under `<slots root>/<repo id>/.locks` cannot be created: fix that folder's permissions.",
    "not_terminal": "The step has not ended: wait for it, `tl plan start` to repeat it, or `tl plan release --abandon`.",
    "entry_running": "Its entry runs: wait, or stop it by verified pid (the `stuck:hung` guide), then run it again.",
    "worker_unknown": "Dispatched with no agent recorded, so it cannot be shown stopped: the whole-DB discard is the only way out.",
    "slot_dirty": "The slot stays held: remove the listed files (nothing is reset for you), then run it again.",
    "remote": "`origin` could not be reached: often credentials; check that `git push` works from this shell, then rerun. The "
    "factory's Git sets `GIT_SSH_COMMAND` (no prompt), which overrides a `core.sshCommand` in your Git config: use ssh-agent or "
    "`~/.ssh/config` for the key.",
    "git": "Git could not run or answer (for a publish, an HTTPS login refused looks like this too): check that `git` and, for a "
    "publish, `git push` work from this shell, then rerun.",
    "repository": "The slot's `.git` pointer or repository is not the attempt's: inspect the slot (`git -C <slot> rev-parse "
    "--git-common-dir`); nothing was pushed.",
    "not_verified": "Only a verified plan is published: `tl plan verify` first; a rejected plan has nothing to publish.",
    "remote_ahead": "The remote task/<id> already holds the verified commit plus later commits: compare them; the factory does "
    "not record it as its publication and never forces.",
    "no_remote": "Add the remote (`git remote add origin <url>`) in the person's checkout, then rerun `tl plan publish`.",
    "branch_moved": "Restore the local task/<id> so it contains the verified commit, then rerun; or `tl plan release --abandon`.",
    "remote_moved": "`git fetch origin task/<id>`, compare it with the verified commit, then rerun `tl plan publish`.",
    "diverged": "The remote task/<id> does not contain the verified commit: compare them, then merge or move the remote branch "
    "aside yourself; the factory never forces.",
    "remote_rejected": "The remote's policy refused it: push the verified commit by hand (`git push origin <commit>:refs/heads/"
    "task/<id>`, never `--force`) to see why.",
}


def discard(db: Path) -> str:
    """The last resort, naming this machine config's resolved factory.db, never another factory's."""
    return "\n".join([
        "Last resort, when `tl plan release --abandon` cannot prove the attempt stopped (`worker_unknown`): the whole-DB discard:",
        "  1. stop every entry and worker by verified pid (`tl plan show` names them);",
        f"  2. delete {db} and its -wal/-shm (this machine config's factory.db, never another factory's);",
        "  3. in the tracker, `bd unclaim <task-id> --if-assignee taskloop` for each claimed task;",
        "  4. inspect each slot worktree, then `tl slot adopt` again.",
        "Never edit rows by hand: a deleted reservation silently fences out a still-running worker.",
    ])


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
    plan = _add(commands, "plan", f"Plan attempts ({PLAN_ONLY})").add_subparsers(dest="operation", required=True)
    start = _add(plan, "start", f"Admit, relaunch or repeat the task's attempt (free slot, tracker claim); {PLAN_ONLY}. {HELD}")
    start.add_argument("task_id", metavar="TASK")
    for flag in ("--backlog", "--tracker-root", "--checkout", "--model", "--effort"):
        start.add_argument(flag, required=True)
    start.add_argument("--minutes", type=int, required=True, help="Deadline of the attempt (or of its repeat), from now")
    _common(start, "--db", "--artifacts")
    status = _add(plan, "show", f"The task's attempt, its entry, result and next step (read-only; {PLAN_ONLY})")
    status.add_argument("task_id", metavar="TASK")
    status.add_argument("--backlog", required=True)
    _common(status, "--db", "--artifacts")
    listing = _add(plan, "list", f"Every task's current attempt with its next step (read-only; {PLAN_ONLY})")
    listing.add_argument("--stuck", action="store_true", help="Only attempts whose next step is stuck:* or unknown")
    _common(listing, "--db")
    verify = _add(plan, "verify", f"Commit the stage's listed files and verify them, then release a clean slot and publish a verified "
                  f"plan ({PLAN_ONLY})")
    verify.add_argument("task_id", metavar="TASK")
    verify.add_argument("--backlog", required=True)
    _common(verify, "--db")
    release = _add(plan, "release", "Release the slot of a step that ended (parked at its base, the claim kept); with --abandon, "
                   f"of any step whose entry and agent are stopped, and return the tracker claim ({PLAN_ONLY})")
    release.add_argument("task_id", metavar="TASK")
    release.add_argument("--backlog", required=True)
    release.add_argument("--abandon", action="store_true", help="Throw the attempt away and give the task back; `tl plan start` "
                         "then admits a fresh attempt")
    _common(release, "--db")
    publish = _add(plan, "publish", "Push the verified plan commit to origin's task/<id> as you, never forced; nothing merges or lands")
    publish.add_argument("task_id", metavar="TASK")
    publish.add_argument("--backlog", required=True)
    _common(publish, "--db")


def _start(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    request = StartRequest(arguments.task_id, arguments.backlog, arguments.tracker_root, Path(arguments.checkout), arguments.model,
                           arguments.effort, arguments.minutes)
    with cli_composition.open_plan_start(loaded.settings.db.value, loaded.settings.artifacts.value) as ports:
        return ports if isinstance(ports, Failed) else plan_ops.start(ports, request)


def _show(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_plan_reads(loaded.settings.db.value) as reads:
        if isinstance(reads, Failed):
            return reads
        return plan_ops.status(reads, loaded.settings.artifacts.value, arguments.backlog, arguments.task_id)


def _list(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_plan_reads(loaded.settings.db.value) as reads:
        return reads if isinstance(reads, Failed) else plan_ops.attempts_status(reads, stuck=arguments.stuck)


def _verify(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_plan_verify(loaded.settings.db.value) as opened:
        return opened if isinstance(opened, Failed) else plan_ops.verify_task(*opened, arguments.backlog, arguments.task_id)


def _release(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_plan_release(loaded.settings.db.value) as opened:
        if isinstance(opened, Failed):
            return opened
        return plan_ops.release_task(*opened, arguments.backlog, arguments.task_id, abandon=arguments.abandon)


def _publish(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_plan_publish(loaded.settings.db.value) as opened:
        return opened if isinstance(opened, Failed) else plan_ops.publish_task(*opened, arguments.backlog, arguments.task_id)


def _adopt(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    settings = loaded.settings
    return cli_composition.adopt(settings.db.value, Path(arguments.checkout), settings.slots_root.value, settings.slot_count.value)


OPERATIONS: dict[tuple[str, str], Callable[[argparse.Namespace, Loaded], Result]] = {
    ("config", "show"): lambda _arguments, loaded: loaded,
    ("slot", "adopt"): _adopt,
    ("plan", "start"): _start,
    ("plan", "show"): _show,
    ("plan", "list"): _list,
    ("plan", "verify"): _verify,
    ("plan", "release"): _release,
    ("plan", "publish"): _publish,
}


def run(arguments: argparse.Namespace) -> int:
    """Resolve the machine config (every command refuses a bad one), run the one operation, render it."""
    flags = Flags(getattr(arguments, "db", None), getattr(arguments, "artifacts", None), getattr(arguments, "root", None),
                  getattr(arguments, "count", None))
    loaded = cli_composition.load_config(arguments.config, flags)
    if isinstance(loaded, ConfigRefused):
        result: Result = plan_ops.refused_config(loaded)
    else:
        result = OPERATIONS[arguments.command, arguments.operation](arguments, loaded)
    stream = sys.stderr if isinstance(result, Failed) else sys.stdout
    if arguments.json_output:
        print(json.dumps(plan_data.as_data(result)), file=stream)
    else:
        if isinstance(result, Failed) and result.claim_leaked:
            task = arguments.task_id
            print(f"the tracker claim on {task} may still be held by taskloop; check `bd show {task}`", file=sys.stderr)
        db = None if isinstance(loaded, ConfigRefused) else loaded.settings.db.value
        print("\n".join(_human(f"tl {arguments.command} {arguments.operation}", result, db)), file=stream)
    return plan_ops.exit_code(result)


def _status_lines(each: AttemptStatus) -> list[str]:
    entry = "" if each.entry_process is None else f" (pid {each.entry_process[0]}, started {each.entry_process[1]})"
    # the stored registration only: the agent may have exited long ago, so it is never shown as running
    worker = "none" if each.worker is None else f"last known pid {each.worker[0]}, process group {each.worker[1]} (not checked)"
    repeats = "" if each.previous_attempt_id is None else f"; repeats {each.previous_attempt_id}, {each.repeat_reason}"
    ended = each.release
    released = [] if ended is None else [
        f"Released: {datetime.fromtimestamp(ended.released_at, UTC):%Y-%m-%d %H:%M:%S} UTC, slot parked at {ended.head}; "
        f"claim {ended.claim}{'; abandoned' if ended.abandoned else ''}"
    ]
    found = each.published
    published = [] if found is None else [
        f"Published: task/{each.task_id} at {found.commit} on origin, {datetime.fromtimestamp(found.published_at, UTC):%Y-%m-%d %H:%M:%S}"
        " UTC"
    ]
    return [
        f"Task: {each.task_id} (backlog {each.backlog})", f"Attempt: {each.attempt_id} ({each.number} of at most {ATTEMPTS}{repeats})",
        *(f"Earlier: {attempt_id} " + ("abandoned" if why == "abandoned" else f"repeated ({why})") for attempt_id, why in each.earlier),
        f"Slot: {each.slot}", f"Phase: {each.phase}",
        f"Entry: {each.entry}{entry}", f"Worker: {worker}", f"Result: {each.result.status} {each.result.reason}".rstrip(),
        f"Succeeded: {'yes' if succeeded(each.result) else 'no'}", f"Deadline passed: {'yes' if each.deadline_passed else 'no'}",
        *released, *published,
    ]


def _human(command: str, result: Result, db: Path | None) -> list[str]:
    """`db` (the resolved factory.db) goes into the discard steps; None only when the config itself was refused."""
    stuck = [] if db is None else [discard(db)]
    match result:
        case Failed(kind=kind, reason=reason):
            word = "uncertain" if kind == "uncertain" else f"{kind}:{reason}"
            lines = [f"{command}: {word}", *([result.detail] if result.detail else [])]
            lines += [f"  {view.name} {view.state} {view.reason or view.attempt_id or ''} {view.path}" for view in result.slots]
            lines += [GUIDE[each] for each in (kind, reason) if each in GUIDE]
            return lines + ([f"Admitted: {HELD} Re-run `tl plan start` to retry the launch."] if result.admitted else [])
        case Started():
            entry = "" if result.entry is None else f"; entry pid {result.entry[0]}"
            lines = [f"{result.status}: attempt {result.attempt_id} for {result.task_id} (backlog {result.backlog}){entry}"]
            lines += [f"Result: {result.result}"] if result.result else []
            if result.number is not None:
                stand = f"attempt {result.number - 1}'s choices stand; deadline from --minutes"
                lines += [f"attempt {result.number} of at most {ATTEMPTS}; {stand}"]
            lines += ["existing attempt; its admitted choices stand"] if result.existing else [HELD]
            return [*lines, f"This runs the {PLAN_ONLY}. Follow it with `tl plan show {result.task_id} --backlog {result.backlog}`."]
        case Shown(status=each):
            paths = [f"Directory: {result.directory}", f"Entry log: {result.entry_log}"]
            ended = each.release
            guide = GUIDE[each.next] if ended is None or not ended.abandoned else GUIDE["abandoned"] if each.next == "start" else UNCLAIMING
            steps = [guide, *(stuck if each.next.startswith("stuck:") else [])]
            left = [f"Unsettled: {each.leftovers[0]}", *(f"  {line}" for line in each.leftovers[1:])] if each.leftovers else []
            last = [] if each.last_entry is None else [f"Last entry result: {each.last_entry}"]
            return [*_status_lines(each), *paths, *last, *left, f"Next: {each.next}", *steps]
        case Listed(attempts=attempts):
            rows = [f"{a.task_id}\t{a.backlog}\t{a.number}/{ATTEMPTS}\t{a.slot}\t{a.phase}\t{a.entry}\t"
                    f"{a.result.status} {a.result.reason}\t{a.next}" for a in attempts]
            kinds = dict.fromkeys(a.next for a in attempts if a.next.startswith("stuck:"))
            steps = [f"{kind}: {GUIDE[kind]}" for kind in kinds] + (stuck if kinds else [])
            return ["task\tbacklog\tattempt\tslot\tphase\tentry\tresult\tnext", *rows, *steps]
        case Checked() | Freed() | PublishedTask():
            return _freed_lines(result)
        case Adoption() | Loaded():
            return _setup_lines(result)


def _freed_lines(result: Checked | Freed | PublishedTask) -> list[str]:
    """A verdict with the release and the publication that followed it; a release with each change on its own line; a
    publication."""
    if isinstance(result, PublishedTask):
        found = result.outcome
        done = "published" if isinstance(found, BranchPublished) else "already_published"
        return [f"{done}: task/{result.task_id} at {found.commit} on origin (attempt {result.attempt_id}, backlog {result.backlog})",
                *(["Nothing changed: it was published before."] if done == "already_published" else [])]
    if isinstance(result, Checked):
        held = [f"Release: {result.release}"] + ([] if result.release == "released" else [GUIDE["release"]])
        held += [f"Publish: {result.published}"] + ([] if result.published == "published" else [PUBLISH])
        return [f"{result.status}: attempt {result.attempt_id} for {result.task_id} (backlog {result.backlog})", *held]
    found, task = result.outcome, result.task_id
    if not isinstance(found, Released):
        return [f"already_released: attempt {result.attempt_id} for {task} (backlog {result.backlog}); nothing changed",
                f"Claim: {found.claim}{'; abandoned' if found.abandoned else ''}"]
    lines = [f"released: attempt {result.attempt_id} for {task} (backlog {result.backlog})"]
    lines += [f"Slot {found.slot} parked at {found.parked}" if found.parked else f"Slot {found.slot}: no Git write"]
    lines += [f"Reservation of {found.slot} removed"] if found.reservation_removed else []
    claims = {"kept": "Claim kept", "unclaimed": "Claim returned to the tracker",
              "not_held": f"Claim not held by taskloop (reverted, or another actor's): check `bd show {task}`"}
    lines += [claims[found.claim]]
    return lines + ([f"Abandoned: `tl plan start {task}` admits a fresh attempt"] if found.abandoned else [])


def _setup_lines(result: Adoption | Loaded) -> list[str]:
    if isinstance(result, Adoption):
        slots = result.slots
        lines = [f"{each.name} {'adopted' if isinstance(each, Adopted) else each.reason} {each.path or ''}".rstrip() for each in slots]
        missing = any(not isinstance(each, Adopted) and each.reason == "not_listed" for each in slots)
        attached = any(not isinstance(each, Adopted) and each.reason == "attached" for each in slots)
        hints = ["Make each not_listed slot with `git worktree add --detach <path>`, then adopt again."] if missing else []
        return lines + hints + (["Run `git switch --detach` in a slot left on a task branch, then adopt again."] if attached else [])
    lines = [f"Config file: {result.path} ({'exists' if result.exists else 'missing: built-in defaults'})"]
    return lines + [f"{key} = {each.value} ({each.source})" for key, each in result.settings.pairs()]
