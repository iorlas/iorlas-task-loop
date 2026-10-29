"""RepoProfile: the repo's .task-loop.json as typed records . An unknown key is an error, not a silent no-op."""
from dataclasses import field, fields
from typing import Any, Literal, TextIO

from taskloop.contracts.argv import FORM, shape_problem, text_of
from taskloop.contracts.codec import CodecError, from_json, record

FRESH_ABOVE_K = {"claude": 150, "codex": 100, "xai": 100}
TEST_PATTERN = r"^\s*(def test_|async def test_|\[(Test|UnityTest|Fact|Theory|TestMethod|TestCase)\b|#\[test\]|(it|test)\(|func Test)"


class ConfigError(ValueError):
    """.task-loop.json is not a RepoProfile (an unknown key is the usual cause)."""


@record
class GateOnly:
    """A command no plan check may run: only the gate at land."""

    argv: list[str]
    why: str = ""

    @property
    def cmd(self) -> str:
        return text_of(self.argv)


@record
class VisualConfig:
    """Globs saying which changes are visual (a look judge reads the pictures)."""

    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@record
class ContainerConfig:
    """Where a check that says `"in": "container"` runs: an image, or a Dockerfile of the repo (built once, tagged by its hash)."""

    image: str = ""
    dockerfile: str = ""


@record
class CheckSpec:
    id: str
    argv: list[str]
    group: Literal["static", "tests", "acceptance"] = "tests"
    when: list[str] = field(default_factory=list)
    retry: int = 0
    wall_min: float | None = None  # this check's wall-time limit; absent: engine.check_wall_min
    cache: bool | None = None
    inputs: list[str] | str = field(default_factory=list)
    inputs_only: bool = False
    exclude: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    writer: bool | None = None  # true: the writer may run it whatever it costs; false: never; absent: by how long it takes
    writer_check_max_s: float | None = None  # this check's own cut for "too slow for the writer" (else engine.writer_check_max_s)
    tail_log: str = ""  # a log of the tree whose first compile errors join this check's red output when it shows none
    where: Literal["host", "container"] = field(default="host", metadata={"name": "in"})  # container: needs engine.container

    @property
    def cmd(self) -> str:
        """The check as one line of text: its id in logs, caches and prompts."""
        return text_of(self.argv)


@record
class SlotsConfig:
    count: int = 0
    dir: str = ".slots"
    base: str = "origin/main"
    setup: list[str] = field(default_factory=list)  # argv
    setup_inputs: list[str] = field(default_factory=list)
    keep: list[str] = field(default_factory=list)


@record
class LoopConfig:
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
    selftest_wait: float = 30
    help_wait: float = 20
    absent: float = 600  # ready beads, no live loop and no beat for this long: the loop is absent
    reload_fallback: float = 120  # a run-task that dies this soon after a re-exec is put back on the version it came from
    keep_days: float = 14  # `tl prune`: run data older than this goes (open or parked beads exempt), and a merged build tree idle this long
    min_free_gb: float = 5  # the loop claims nothing, and exits 0, while the config dir's disk has less free than this
    build_dir: str = "~/Workspaces/wt"  # `tl prune` removes merged, clean worktrees under here (never a loop slot)


@record
class EngineConfig:
    """The `engine` block; every key has the default the engine uses today."""

    gate: list[str] = field(default_factory=list)  # argv; empty: no gate
    land: list[str] = field(default_factory=lambda: ["git", "push", "origin", "HEAD:main"])
    base: str = "origin/main"
    check_links: bool = True
    pick_label: str = ""
    needs_info_label: str = "needs-info"
    skip_labels: list[str] = field(default_factory=list)
    epic_order: list[str] = field(default_factory=list)
    epic_only: bool = False
    gate_only: list[GateOnly] = field(default_factory=list)
    reflect: bool = True
    planner_notes: str = ""
    shot_table: str = ""
    write_fresh_stage_k: float = 100
    write_fresh_above_k: float | dict[str, float] = field(default_factory=lambda: dict(FRESH_ABOVE_K))
    delegate: str = ""
    untracked_ignore: list[str] = field(default_factory=list)
    checks: list[CheckSpec] = field(default_factory=list)
    container: ContainerConfig | None = None
    host: bool = False
    worker_rules: str = ""
    test_pattern: str = TEST_PATTERN
    area_label_prefix: str = ""
    areas: dict[str, Any] = field(default_factory=dict)
    evidence_dir: str = ""
    visual_paths: VisualConfig | None = None
    budget_usd: float = 15
    budget_min: float = 180
    budget_min_by_label: dict[str, float] = field(default_factory=dict)
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
    max_total_reviews: int = 12  # reviews in all of a run, replans included: then stop and ask (0: never)
    check_wall_min: float = 60  # a check is stopped only when it runs this long; a quiet or idle one is never stopped before
    gate_timeout_min: float = 90
    lane_wait_min: float = 10
    look_rounds: int = 2
    look_max_px: int = 1280
    brief_kb: float = 5
    evidence_cap_mb: float = 200  # the new bytes of evidence one run keeps (twins are links); the rest is dropped and counted in the log

    @property
    def gate_text(self) -> str:
        """The gate as one line of text ('' when there is none)."""
        return text_of(self.gate) if self.gate else ""


@record
class RepoProfile:
    """A person writes the file, so it carries no `v`."""

    engine: EngineConfig = field(default_factory=EngineConfig)
    slots: SlotsConfig = field(default_factory=SlotsConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)


def _string_commands(data: Any) -> list[str]:
    """Where the profile still has a command as a string: every command is an argv list."""
    root = data if isinstance(data, dict) else {}
    eng_name, slots_name = (f.name for f in fields(RepoProfile)[:2])  # the first two fields: engine, slots
    eng, slots = root.get(eng_name), root.get(slots_name)
    eng, slots = (eng if isinstance(eng, dict) else {}), (slots if isinstance(slots, dict) else {})
    found = [f"{eng_name}.{k}" for k in ("gate", "land") if isinstance(eng.get(k), str)]
    found += [f"{eng_name}.checks[{n}].cmd" for n, c in enumerate(eng.get("checks") or []) if isinstance(c, dict) and "cmd" in c]
    found += [f"{eng_name}.gate_only[{n}]" for n, c in enumerate(eng.get("gate_only") or [])
              if isinstance(c, str) or (isinstance(c, dict) and "cmd" in c)]
    if isinstance(slots.get("setup"), str):
        found.append(f"{slots_name}.setup")
    return found


ENG = next(f.name for f in fields(RepoProfile))  # the profile's first block, engine
RETIRED_ENGINE = ("check_idle_min",)  # keys that once did something and now do nothing: loaded without them, not an error
RETIRED_CHECK = ("idle_min",)  # the same, on one entry of engine.checks
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


def load(data: Any, say_to: TextIO | None = None) -> RepoProfile:
    """The repo's .task-loop.json (parsed) as a RepoProfile; ConfigError names the offending key. With `say_to`, a retired key
    is said there once per process."""
    if say_to:
        say_retired(data, say_to)
    data = _without_retired(data)
    moved = renamed_keys(data)
    if moved:
        raise ConfigError("the repo profile: " + "; ".join(moved))
    old = _string_commands(data)
    if old:
        raise ConfigError(f"the repo profile: {', '.join(old)} is a string command: {FORM}")
    try:
        profile = from_json(RepoProfile, data or {})
    except CodecError as e:
        raise ConfigError(f"the repo profile: {e}") from None
    box = profile.engine.container
    if box and bool(box.image) == bool(box.dockerfile):
        raise ConfigError("the repo profile: engine.container takes exactly one of image or dockerfile")
    boxed = [k.id for k in profile.engine.checks if k.where == "container"]
    if boxed and not box:
        raise ConfigError(f"the repo profile: check {boxed[0]} says \"in\": \"container\" but engine.container is not set")
    cmds = [k.argv for k in profile.engine.checks] + [g.argv for g in profile.engine.gate_only] + [profile.engine.land]
    cmds += [c for c in (profile.engine.gate, profile.slots.setup) if c]
    bad = [shape_problem(c) for c in cmds]
    if any(bad):
        raise ConfigError("the repo profile: " + next(b for b in bad if b))
    return profile
