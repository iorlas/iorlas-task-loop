"""RepoProfile: the repo's .task-loop.json as typed records . An unknown key is an error, not a silent no-op."""
from graphlib import CycleError, TopologicalSorter
from typing import Any, Final, Literal, TextIO, final

import msgspec

from taskloop.contracts import wire
from taskloop.contracts.argv import FORM, shape_problem, text_of
from taskloop.contracts.ids import CheckId, mangle
from taskloop.contracts.wire import Rec

FRESH_ABOVE_K: Final = {"claude": 150.0, "codex": 100.0, "xai": 100.0}
TEST_PATTERN = r"^\s*(def test_|async def test_|\[(Test|UnityTest|Fact|Theory|TestMethod|TestCase)\b|#\[test\]|(it|test)\(|func Test)"


class ConfigError(ValueError):
    """.task-loop.json is not a RepoProfile (an unknown key is the usual cause)."""


SLOT_PLACEHOLDERS: Final = ("slot", "slot_dir", "repo")


def fill_slot_env(values: Any, **names: str) -> dict[str, str]:
    """engine.slot_env with {slot} {slot_dir} {repo} filled in; ConfigError for any other placeholder (or a stray brace)."""
    out: dict[str, str] = {}
    for key, value in values.items():
        try:
            out[key] = value.format(**names)
        except (KeyError, IndexError, ValueError, AttributeError) as e:
            allowed = ", ".join("{" + n + "}" for n in SLOT_PLACEHOLDERS)
            raise ConfigError(f"the repo profile: engine.slot_env.{key} = {value!r}: only {allowed} can be used "
                              f"({type(e).__name__}: {e})") from None
    return out


@final
class VisualConfig(Rec):
    """Globs saying which changes are visual (a look judge reads the pictures)."""

    include: list[str] = msgspec.field(default_factory=list)
    exclude: list[str] = msgspec.field(default_factory=list)


@final
class ReviewSkipConfig(Rec):
    """Globs of the paths a stage may change and still skip its review (engine.skip_review). A stage skips only when EVERY changed
    path is a 100% rename, a formatter-only change, or matches one of these; docs and the profile itself never do. An unknown key
    is an error."""

    config: list[str] = msgspec.field(default_factory=list)
    generated: list[str] = msgspec.field(default_factory=list)
    tools: list[str] = msgspec.field(default_factory=list)
    tests: list[str] = msgspec.field(default_factory=list)


@final
class ContainerConfig(Rec):
    """Where a check that says `"in": "container"` runs: an image, or a Dockerfile of the repo (built once, tagged by its hash)."""

    image: str = ""
    dockerfile: str = ""


@final
class ResourceSpec(Rec):
    """One scarce tool a check can need (engine.resources): at most `limit` checks hold it at once on a machine, across slots."""

    limit: int = 1


@final
class HostResources(Rec):
    """~/.config/task-loop/host.json, written by a person per machine: the resources this host has. The file absent means the host has
    every resource the repo declares; `{"resources": []}` is a host with none (checks that need one are deferred)."""

    resources: list[str] = msgspec.field(default_factory=list)


@final
class CheckSpec(Rec):
    id: CheckId
    argv: list[str]
    group: Literal["static", "tests", "acceptance"] = "tests"
    run: Literal["stage", "gate", "both"] = "stage"  # stage: the round after each write; gate: land's gate steps (and `tl check`); both
    when: list[str] = msgspec.field(default_factory=list)
    retry: int = 0
    wall_min: float | None = None  # this check's wall-time limit; absent: engine.check_wall_min
    cache: bool | None = None
    inputs: list[str] | str = msgspec.field(default_factory=list)
    inputs_only: bool = False
    exclude: list[str] = msgspec.field(default_factory=list)
    env: dict[str, str] = msgspec.field(default_factory=dict)
    writer: bool | None = None  # true: the writer may run it whatever it costs; false: never; absent: by how long it takes
    writer_check_max_s: float | None = None  # this check's own cut for "too slow for the writer" (else engine.writer_check_max_s)
    tail_log: str = ""  # a log of the tree whose first compile errors join this check's red output when it shows none
    keep: list[str] = msgspec.field(default_factory=list)  # tree globs (a Unity log, a result XML) copied after each attempt
    where: Literal["host", "container"] = msgspec.field(default="host", name="in")  # container: needs engine.container
    why: str = ""  # run gate: why no plan check may run this command (it is told to the planner)
    reads: list[CheckId] = msgspec.field(default_factory=list)  # checks whose log and exit code it reads: it runs after them
    lane: str = ""  # checks of one lane run in order, lanes run in parallel; the first red cancels the other lanes ("": the default lane)
    needs: list[str] = msgspec.field(default_factory=list)  # engine.resources it holds a machine-wide lease on while it runs
    # argv run in the worktree before the checks (a formatter); what it changes is checked
    fix: list[str] = msgspec.field(default_factory=list)

    @property
    def cmd(self) -> str:
        """The check as one line of text: its id in logs, caches and prompts."""
        return text_of(self.argv)


@final
class SlotsConfig(Rec):
    count: int = 0
    dir: str = ".slots"
    base: str = "origin/main"
    setup: list[str] = msgspec.field(default_factory=list)  # argv
    setup_inputs: list[str] = msgspec.field(default_factory=list)
    keep: list[str] = msgspec.field(default_factory=list)


@final
class LoopConfig(Rec):
    """The `loop` block: the loop's constants. A key left out keeps the code default; read again at every tick."""

    poll: float = 2  # seconds between looks at a running child (stop command, slot lease)
    heartbeat: float = 60  # the slot bead's lease is kept alive this often while a bead runs
    drained_poll: float = 300  # --wait-drained: how often an empty queue is looked at again
    pause_retry: float = 900  # a bead another session holds, or a pause with no delegate to ask: try it again after this
    gate_cache: float = 30  # delegate's role view is looked at no more often than this
    gate_unknown: float = 900  # a role delegate cannot judge is tried again after this long (unknown fails open)
    net_probe: float = 60  # while the network is down the loop looks every this many seconds
    beat_every: float = 60  # the state file's beat is refreshed at most this often
    logs_kept: int = 5
    slot_fails_to_set_aside: int = 2  # instant failures in a row on one slot that set it aside
    quick_fail_min: float = 1.5  # a failed run shorter than this, in minutes, is an instant failure
    slot_aside_min: float = 720
    fails_to_stop: int = 2  # runs in a row that gave no verdict that stop the loop
    pauses_to_rest: int = 3  # a bead paused this often in one loop run rests for `rest`
    rest: float = 3600
    area_poll: float = 60
    area_say: float = 600
    fault_cooldown: float = 1800
    absent: float = 600  # ready beads, no live loop and no beat for this long: the loop is absent
    reload_fallback: float = 120  # a run-task that dies this soon after a re-exec is put back on the version it came from
    keep_days: float = 14  # `tl prune`: run data past this goes (30 days at least; not a bead not closed), a merged tree idle this long
    min_free_gb: float = 5  # the loop claims nothing, and exits 0, while the config dir's disk has less free than this
    build_dir: str = "~/Workspaces/wt"  # `tl prune` removes merged, clean worktrees under here (never a loop slot)


@final
class EngineConfig(Rec):
    """The `engine` block; every key has the default the engine uses today."""

    land: list[str] = msgspec.field(default_factory=lambda: ["git", "push", "origin", "HEAD:main"])
    land_optimistic_tries: int = 2  # gate re-runs outside the land lock when main moved under it, then inside (0: inside)
    base: str = "origin/main"
    check_links: bool = True
    pick_label: str = ""
    needs_info_label: str = "needs-info"
    skip_labels: list[str] = msgspec.field(default_factory=list)
    epic_order: list[str] = msgspec.field(default_factory=list)
    epic_only: bool = False
    reflect: bool = True
    writer_family: list[str] = msgspec.field(default_factory=list)  # e.g. ["openai"]: --only-family on every worker call
    planner_notes: str = ""
    shot_table: str = ""
    write_fresh_stage_k: float = 100
    write_fresh_above_k: float | dict[str, float] = msgspec.field(default_factory=lambda: dict(FRESH_ABOVE_K))
    delegate: str = ""
    untracked_ignore: list[str] = msgspec.field(default_factory=list)
    checks: list[CheckSpec] = msgspec.field(default_factory=list)
    # added to (over) the slot's environment; {slot} {slot_dir} {repo} filled in
    slot_env: dict[str, str] = msgspec.field(default_factory=dict)
    container: ContainerConfig | None = None
    host: bool = False
    worker_rules: str = ""
    test_pattern: str = TEST_PATTERN
    area_label_prefix: str = ""
    areas: dict[str, Any] = msgspec.field(default_factory=dict)
    visual_paths: VisualConfig | None = None
    budget_usd: float = 15
    budget_min: float = 180
    budget_min_by_label: dict[str, float] = msgspec.field(default_factory=dict)
    bead_token_cap: int = 0  # tokens (in + out) a bead may use over all its runs: at the cap no worker starts (0: no cap)
    max_rounds: int = 3
    max_check_tries: int = 3
    max_replans: int = 2
    max_fix_rounds: int = 2
    max_stages: int = 3
    node_timeout_min: float = 45
    review_budget_min: float = 10  # a reviewer call (review, verify, look) over this is stopped through delegate (Overrun): next rung
    write_idle_min: float = 25  # a write worker silent this long is hung: passed to delegate as --idle, which stops it (a typed stop)
    write_cap_min: float = 120  # the one wall cap of a write call: --timeout
    writer_check_max_s: float = 60
    base_red: bool = True  # a check's first red is run once on the untouched base: red there too, it is not the writer's
    max_same_red: int = 3  # rounds in a row that end red with the same checks and output: then stop and ask (0: never)
    skip_review: ReviewSkipConfig = msgspec.field(default_factory=ReviewSkipConfig)
    review: Literal["on", "off", "sampled"] = "on"  # off: no review call (label review-off: per bead); sampled: review_every
    review_every: int = 3  # sampled: every Nth stage is reviewed, and the last one always
    max_total_reviews: int = 12  # reviews in all of a run, replans included: then stop and ask (0: never)
    check_wall_min: float = 60  # a check is stopped only when it runs this long; a quiet or idle one is never stopped before
    gate_timeout_min: float = 90
    lane_wait_min: float = 10
    look_rounds: int = 2
    look_max_px: int = 1280
    brief_kb: float = 5
    resources: dict[str, ResourceSpec] = msgspec.field(default_factory=dict)  # scarce tools: name -> limit per machine
    evidence_cap_mb: float = 200  # the new bytes of evidence one run keeps (twins are links); the rest is dropped and counted in the log

    @property
    def gate_checks(self) -> list[CheckSpec]:
        """The gate's steps, in the registry's order: the checks that say run gate or both. None: no gate."""
        return [k for k in self.checks if k.run != "stage"]

    @property
    def stage_checks(self) -> list[CheckSpec]:
        """The checks of a stage's round: run stage or both."""
        return [k for k in self.checks if k.run != "gate"]

    @property
    def gate_text(self) -> str:
        """The gate as one line of text ('' when there is none): its steps' commands."""
        return "; ".join(k.cmd for k in self.gate_checks)


@final
class RepoProfile(Rec):
    """A person writes the file, so it carries no `v`."""

    engine: EngineConfig = msgspec.field(default_factory=EngineConfig)
    slots: SlotsConfig = msgspec.field(default_factory=SlotsConfig)
    loop: LoopConfig = msgspec.field(default_factory=LoopConfig)


def _string_commands(data: Any) -> list[str]:
    """Where the profile still has a command as a string: every command is an argv list."""
    root = data if isinstance(data, dict) else {}
    eng_name, slots_name = list(wire.names(RepoProfile))[:2]  # the first two fields: engine, slots
    eng, slots = root.get(eng_name), root.get(slots_name)
    eng, slots = (eng if isinstance(eng, dict) else {}), (slots if isinstance(slots, dict) else {})
    found = [f"{eng_name}.land"] if isinstance(eng.get("land"), str) else []
    found += [f"{eng_name}.checks[{n}].cmd" for n, c in enumerate(eng.get("checks") or []) if isinstance(c, dict) and "cmd" in c]
    if isinstance(slots.get("setup"), str):
        found.append(f"{slots_name}.setup")
    return found


ENG: Final = next(iter(wire.names(RepoProfile)))  # the profile's first block, engine
RETIRED_ENGINE: Final = ("check_idle_min",)  # keys that once did something and now do nothing: loaded without them, not an error
RETIRED_CHECK: Final = ("idle_min",)  # the same, on one entry of engine.checks
GONE_ENGINE: Final = {  # key -> what to do instead: refused at load (the old spelling is not read)
    "gate": "engine.gate is gone: move the gate's steps into engine.checks, each with \"run\": \"gate\" (or \"both\") and its argv",
    "gate_only": "engine.gate_only is gone: a command only the gate runs is a check in engine.checks with \"run\": \"gate\"",
}
RENAMED_ENGINE: dict[str, str] = {"check_timeout_min": "check_wall_min"}  # old key -> new key: the old one fails, naming the new
RENAMED_CHECK: dict[str, str] = {"timeout_min": "wall_min"}  # the same, on one entry of engine.checks


def renamed_keys(data: Any) -> list[str]:
    """One message per renamed key a parsed .task-loop.json still carries, e.g. `checks[5]: timeout_min was renamed to wall_min`."""
    eng = data.get(ENG) if isinstance(data, dict) else None
    if not isinstance(eng, dict):
        return []
    found = [f"{ENG}: {k} was renamed to {new}" for k, new in RENAMED_ENGINE.items() if k in eng]
    for n, c in enumerate(eng.get("checks") or []):
        found += [f"checks[{n}]: {k} was renamed to {new}" for k, new in RENAMED_CHECK.items() if isinstance(c, dict) and k in c]
    return found


def retired_keys(data: Any) -> list[str]:
    """The retired keys a parsed .task-loop.json still carries, spelled as `engine.check_idle_min` and `engine.checks[0].idle_min`."""
    eng = data.get(ENG) if isinstance(data, dict) else None
    if not isinstance(eng, dict):
        return []
    found = [f"{ENG}.{k}" for k in RETIRED_ENGINE if k in eng]
    for n, c in enumerate(eng.get("checks") or []):
        found += [f"{ENG}.checks[{n}].{k}" for k in RETIRED_CHECK if isinstance(c, dict) and k in c]
    return found


_SAID: set[str] = set()


def say_retired(data: Any, out: TextIO) -> None:
    """One line on `out` per retired key of `data` not yet said in this process."""
    for k in retired_keys(data):
        if k not in _SAID:
            _SAID.add(k)
            print(f"task-loop: .task-loop.json: {k} is retired and ignored; safe to delete", file=out)


def _without_retired(data: Any) -> Any:
    """`data` less its retired keys; `data` itself is left as it was."""
    if not retired_keys(data):
        return data
    eng = {k: v for k, v in data[ENG].items() if k not in RETIRED_ENGINE}
    if isinstance(eng.get("checks"), list):
        eng["checks"] = [{k: v for k, v in c.items() if k not in RETIRED_CHECK} if isinstance(c, dict) else c for c in eng["checks"]]
    return {**data, ENG: eng}


def graph_problem(checks: list[CheckSpec]) -> str:
    """Why the registry's checks are not a graph the engine can order ('' when they are): an id twice, two ids that become one
    environment name ($TL_CHECK_LOG_<ID>), a read of a check that is not there, or a cycle of reads. Judged once, at load."""
    names: dict[str, CheckId] = {}
    for k in checks:
        if k.id in names.values():
            return f"check id {k.id} is used twice in engine.checks"
        other = names.setdefault(mangle(k.id), k.id)
        if other != k.id:
            return f"check ids {other} and {k.id} both become $TL_CHECK_LOG_{mangle(k.id)}: rename one"
    known = {k.id for k in checks}
    for k in checks:
        gone = [r for r in k.reads if r not in known]
        if gone:
            return f"check {k.id} reads {gone[0]}, which engine.checks does not have"
        lane = {c.id: c.lane for c in checks}
        apart = [r for r in k.reads if lane[r] != k.lane]
        if apart:
            return (f"check {k.id} (lane {k.lane!r}) reads {apart[0]} of lane {lane[apart[0]]!r}: "
                    "lanes run at the same time, a read stays in its lane")
    try:
        TopologicalSorter({k.id: k.reads for k in checks}).prepare()
    except CycleError as e:
        return "checks read each other in a cycle: " + " -> ".join(e.args[1])
    return ""


def resource_problem(eng: EngineConfig) -> str:
    """Why engine.resources and the checks' `needs` do not fit ('' when they do): a limit under 1, or a need nobody declared."""
    for name, r in eng.resources.items():
        if r.limit < 1:
            return f"engine.resources.{name}.limit must be at least 1"
    for k in eng.checks:
        lost = [n for n in k.needs if n not in eng.resources]
        if lost:
            return f"check {k.id} needs {lost[0]}, which engine.resources does not declare"
    return ""


def load(data: Any, say_to: TextIO | None = None) -> RepoProfile:
    """The repo's .task-loop.json (parsed) as a RepoProfile; ConfigError names the offending key. With `say_to`, a retired key
    is said there once per process."""
    if say_to:
        say_retired(data, say_to)
    data = _without_retired(data)
    moved = renamed_keys(data)
    if moved:
        raise ConfigError("the repo profile: " + "; ".join(moved))
    eng_data = data.get(ENG) if isinstance(data, dict) else None
    gone = [why for k, why in GONE_ENGINE.items() if isinstance(eng_data, dict) and k in eng_data]
    if gone:
        raise ConfigError("the repo profile: " + "; ".join(gone))
    old = _string_commands(data)
    if old:
        raise ConfigError(f"the repo profile: {', '.join(old)} is a string command: {FORM}")
    try:
        profile = wire.load(RepoProfile, data or {})
    except ValueError as e:
        raise ConfigError(f"the repo profile: {e}") from None
    box = profile.engine.container
    if box and bool(box.image) == bool(box.dockerfile):
        raise ConfigError("the repo profile: engine.container takes exactly one of image or dockerfile")
    boxed = [k.id for k in profile.engine.checks if k.where == "container"]
    if boxed and not box:
        raise ConfigError(f"the repo profile: check {boxed[0]} says \"in\": \"container\" but engine.container is not set")
    bad_needs = resource_problem(profile.engine)
    if bad_needs:
        raise ConfigError(f"the repo profile: {bad_needs}")
    bad_graph = graph_problem(profile.engine.checks)
    if bad_graph:
        raise ConfigError(f"the repo profile: {bad_graph}")
    fill_slot_env(profile.engine.slot_env, **dict.fromkeys(SLOT_PLACEHOLDERS, ""))
    cmds = [k.argv for k in profile.engine.checks] + [profile.engine.land]
    cmds += [k.fix for k in profile.engine.checks if k.fix]
    cmds += [c for c in (profile.slots.setup,) if c]
    bad = [shape_problem(c) for c in cmds]
    if any(bad):
        raise ConfigError("the repo profile: " + next(b for b in bad if b))
    return profile
