"""RepoProfile: the repo's .task-loop.json as typed records . An unknown key is an error, not a silent no-op."""
from dataclasses import field
from typing import Any, Literal

from taskloop.contracts.codec import CodecError, from_json, record

FRESH_ABOVE_K = {"claude": 150, "codex": 100, "xai": 100}
TEST_PATTERN = r"^\s*(def test_|async def test_|\[(Test|UnityTest|Fact|Theory|TestMethod|TestCase)\b|#\[test\]|(it|test)\(|func Test)"


class ConfigError(ValueError):
    """.task-loop.json is not a RepoProfile (an unknown key is the usual cause)."""


@record
class GateOnly:
    """A command no plan check may run: only the gate at land."""

    cmd: str
    why: str = ""


@record
class VisualConfig:
    """Globs saying which changes are visual (a look judge reads the pictures)."""

    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@record
class CheckSpec:
    id: str
    cmd: str
    group: Literal["static", "tests", "acceptance"] = "tests"
    when: list[str] = field(default_factory=list)
    retry: int = 0
    timeout_min: float | None = None
    idle_min: float | None = None
    cache: bool | None = None
    inputs: list[str] | str = field(default_factory=list)
    inputs_only: bool = False
    exclude: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@record
class SlotsConfig:
    count: int = 0
    dir: str = ".slots"
    base: str = "origin/main"
    setup: str = ""
    setup_inputs: list[str] = field(default_factory=list)
    keep: list[str] = field(default_factory=list)


@record
class EngineConfig:
    """The `engine` block; every key has the default the engine uses today."""

    gate: str = ""
    land: str = "git push origin HEAD:main"
    base: str = "origin/main"
    check_links: bool = True
    pick_label: str = ""
    needs_info_label: str = "needs-info"
    skip_labels: list[str] = field(default_factory=list)
    epic_order: list[str] = field(default_factory=list)
    epic_only: bool = False
    gate_only: list[str | GateOnly] = field(default_factory=list)
    reflect: bool = True
    planner_notes: str = ""
    shot_table: str = ""
    write_fresh_stage_k: float = 100
    write_fresh_above_k: float | dict[str, float] = field(default_factory=lambda: dict(FRESH_ABOVE_K))
    delegate: str = ""
    untracked_ignore: list[str] = field(default_factory=list)
    checks: list[CheckSpec] = field(default_factory=list)
    host: bool = False
    no_sandbox: bool = False
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
    write_idle_warn_min: float = 15
    write_idle_stop_min: float = 25
    write_cap_min: float = 120
    writer_check_max_s: float = 60
    check_timeout_min: float = 60
    check_idle_min: float = 10
    gate_timeout_min: float = 90
    lane_wait_min: float = 10
    look_rounds: int = 2
    look_max_px: int = 1280
    brief_kb: float = 5


@record
class RepoProfile:
    """A person writes the file, so it carries no `v`."""

    engine: EngineConfig = field(default_factory=EngineConfig)
    slots: SlotsConfig = field(default_factory=SlotsConfig)


def load(data: Any) -> RepoProfile:
    """The repo's .task-loop.json (parsed) as a RepoProfile; ConfigError names the offending key."""
    try:
        return from_json(RepoProfile, data or {})
    except CodecError as e:
        raise ConfigError("the repo profile: %s" % e) from None
