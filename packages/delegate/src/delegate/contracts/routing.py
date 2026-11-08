"""The routing table (`routing.json` + the owner's `config.json` overrides, validated at load) and the router's answer.

`Routing` is read, never written. The owner's `profile` (account choices, acks) is not a setting and never reaches `Settings`. A router
`Decision` is `Run | Stop | AccountOut | Error`; `as_dict()` is the JSON that `route.py next` prints.
"""

from dataclasses import field

from delegate.contracts.codec import record
from delegate.contracts.json_types import Json

V = 1

# Settings keys an older config.json or routing.json may still carry. Loading drops them with one warning each; any other unknown key fails.
# Recognized only to refuse the stored shape, never to read or convert it.
RETIRED_ROUTING = {"la" + "nes": "accounts"}

RETIRED_SETTINGS = (
    "codex_weekly_used_override",
    "codex_resume_after_stall",
    "claude_resume_after_stall",
    "opencode_resume_after_stall",
    "codex_plan_review_only",
    "host_accounts",
    "contained_network",
    "cache_roots",
    "credit",
)


def replaced_settings(accounts: dict[str, dict[str, Json]]) -> dict[str, str]:
    """The per-account enable settings an old config.json may carry (`<account>_enabled`, from the account name) -> the account. They
    moved to the account profile: loading fails loudly with the exact fix, the old key is never honored."""
    return {f"{n.removesuffix('_SUBSCRIPTION').lower()}_enabled": n for n, spec in accounts.items() if spec.get("opt_in")}


def split_retired(settings: dict[str, Json]) -> tuple[dict[str, Json], list[str]]:
    """(settings without the retired keys, the retired keys that were there, in file order)."""
    for old, new in RETIRED_ROUTING.items():
        if old in settings:
            raise ValueError(f"routing.json: rename the top-level key '{old}' to '{new}'")
    gone = [k for k in settings if k in RETIRED_SETTINGS]
    return {k: v for k, v in settings.items() if k not in RETIRED_SETTINGS}, gone


@record
class Gate:
    weekly: float
    five_hour: float


@record
class Ceiling:
    five_hour: float
    weekly: float
    orchestrator_five_hour: float
    orchestrator_weekly: float


@record
class Strain:
    five_hour: float
    weekly_pace: float


@record
class Burn:
    minutes: float
    min_left_percent: float


@record
class BreakerPolicy:
    n: int = 3
    window_min: float = 10
    ladder_min: tuple[float, ...] = (15, 30, 60)
    credit_probe_s: float = 6 * 3600
    logout_s: float = 900
    guess_s: float = 15 * 60
    stale_usage_s: float = 6 * 3600


@record
class Settings:
    orchestrator_reserve: Gate
    worker_account_gate: Gate
    relaxed_ceiling: Ceiling
    strain: Strain
    recover: Strain
    burn: Burn
    max_parallel: int | None
    min_dwell_minutes: float
    usage_stale_minutes: float
    fresh_above_k: dict[str, float] = field(default_factory=lambda: {"claude": 150.0, "openai": 100.0, "xai": 100.0})
    fresh_stage_k: float = 100.0
    claude_weekly_reset: str = ""
    breaker: BreakerPolicy = field(default_factory=BreakerPolicy)
    writer_family: list[str] = field(default_factory=list)
    writer_exec_allow: list[list[str]] = field(default_factory=list)
    writer_read_roots: list[str] = field(default_factory=list)


@record
class ModelSpec:
    family: str
    api: str
    agent: str | None = None
    cost: float = 1000
    loop: bool = True


@record
class AccountSpec:
    family: str
    kind: str
    reader: str
    runner: str
    label: str = ""
    ready: str = ""
    shared_with_orchestrator: bool = False
    opt_in: bool = False  # off until profile.accounts.<account> is "enabled"; others turn on when ready


@record
class Step:
    model: str
    effort: str
    on: str
    mode: str = "read_only"
    cap: float | None = None
    flag: str | None = None
    idx: int | None = None


@record
class Role:
    about: str
    advance: str
    stop: str
    steps: tuple[Step, ...] = ()
    by_author: dict[str, tuple[Step, ...]] | None = None
    degraded_needs_consent: tuple[Step, ...] = ()
    exclude_families: tuple[str, ...] = ()
    order: str | None = None


@record
class Routing:
    V = V
    settings: Settings
    models: dict[str, ModelSpec]
    accounts: dict[str, AccountSpec]
    roles: dict[str, Role]
    premium: dict[str, Step | None]


@record
class CallArgs:
    """What the caller asked for, as the router sees it (no argv, no paths)."""

    authored_by: str | None = None
    premium: str | None = None
    allow_degraded: bool = False
    unattended: bool = False
    resume: str | None = None
    cap: float | None = None
    only_family: tuple[str, ...] = ()  # the families a call may use: the role's steps are filtered to them, no fallback outside
    engine_only: tuple[str, ...] = ()  # recipes only the engine runs: a write step needs an account whose harness can deny them
    engine_only_advisory: bool = False  # allow unsupported write accounts with an explicit warning


@record
class AskUser:
    question: str
    options: tuple[str, ...]
    then: str


@record
class Run:
    role: str
    account: str
    model: str
    effort: str
    mode: str
    pass_: str  # strict | relaxed | resume
    rung: int | None = None
    fallback: bool | None = None
    fallback_reason: str | None = None
    first_account: str | None = None
    cap: float | None = None
    flag: str | None = None
    warning: str | None = None
    trace: tuple[str, ...] | None = None  # None: a resume plan reasoned about nothing

    def as_dict(self) -> dict[str, Json]:
        d: dict[str, Json] = {
            "action": "run",
            "role": self.role,
            "pass": self.pass_,
            "rung": self.rung,
            "fallback": self.fallback,
            "fallback_reason": self.fallback_reason,
            "first_account": self.first_account,
            "account": self.account,
            "model": self.model,
            "effort": self.effort,
            "mode": self.mode,
            "cap": self.cap,
        }
        if self.pass_ != "resume" or self.flag is not None:
            d["flag"] = self.flag
        if self.trace is not None:
            d["trace"] = list(self.trace)
        if self.warning:
            d["warning"] = self.warning
        return d


@record
class Stop:
    """No account can take the call now (reason None), or the role's first choice only waits for a slot (reason busy)."""

    say: str
    role: str | None = None
    reason: str | None = None
    account: str | None = None
    retry_after: float | None = None
    resets: dict[str, str] = field(default_factory=dict)
    ask_user: AskUser | None = None
    trace: tuple[str, ...] | None = None

    def as_dict(self) -> dict[str, Json]:
        d: dict[str, Json] = {"action": "stop"}
        if self.reason == "busy":
            d |= {"reason": "busy", "account": self.account, "retry_after": self.retry_after, "say": self.say}
            extra: dict[str, Json] = {} if self.trace is None else {"trace": list(self.trace)}
            return d | extra
        d |= {"role": self.role, "say": self.say, "resets": dict(self.resets), "trace": list(self.trace or ())}
        if self.reason:
            d["reason"] = self.reason
        if self.ask_user:
            d["ask_user"] = {"question": self.ask_user.question, "options": list(self.ask_user.options), "then": self.ask_user.then}
        return d


@record
class AccountOut:
    """`--resume` on an account that is held, out, benched or logged out: the thread stays on its account, the call is refused with
    `outcome`."""

    account: str
    outcome: str
    say: str
    retry_after: float | None = None

    def as_dict(self) -> dict[str, Json]:
        return {"action": "stop", "account": self.account, "retry_after": self.retry_after, "outcome": self.outcome, "say": self.say}


@record
class Error:
    error: str

    def as_dict(self) -> dict[str, Json]:
        return {"action": "error", "error": self.error}


Decision = Run | Stop | AccountOut | Error
