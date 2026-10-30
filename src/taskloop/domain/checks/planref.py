"""The plan's checks against the registry: which checks a plan names, what the registry refuses of them (a ref to a check that is not
one, a read of one, a wrapper of one's command), and the commands a worker is told. Pure."""
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, assert_never

from taskloop.contracts.config import CheckSpec, EngineConfig
from taskloop.contracts.ids import CheckId
from taskloop.contracts.plancheck import Adhoc, PlanCheck, Ref
from taskloop.domain.checks.cmd import matchers as sh
from taskloop.domain.checks.names import log_var, rc_var
from taskloop.domain.matchers import clip

JUST_PLAIN_FLAGS: Final = frozenset({"--unstable", "-q", "--quiet", "-v", "--verbose", "--dry-run", "-n", "--no-deps", "--highlight",
                                     "--no-highlight"})


type Plan = Mapping[str, Any]  # the plan after parse: every check in it is a PlanCheck


def plan_checks(plan: Plan) -> list[PlanCheck]:
    """The plan's checks, once each: stages, risks, cases."""
    return list(dict.fromkeys([c for s in plan.get("stages") or [] for c in s["checks"]] + [
        x["check"] for k in ("risks", "cases") for x in plan.get(k) or []
        if x.get("check") and x.get("class", "test") == "test"
        and x.get("proved_by", "check") in ("check", "stage")]))  # a look, taste, leftover or engine-step case has no command


def adhocs(checks: Iterable[PlanCheck]) -> list[Adhoc]:
    """The checks that are commands of the plan's own, once each (a ref is a registered check: the round runs it anyway)."""
    return list(dict.fromkeys(c for c in checks if isinstance(c, Adhoc)))


def registry(cfg: EngineConfig) -> dict[CheckId, CheckSpec]:
    """The checks a plan may name: the ones a stage's round runs."""
    return {k.id: k for k in cfg.stage_checks}


def commands(checks: Iterable[PlanCheck], cfg: EngineConfig) -> list[str]:
    """What a worker or the land runs for these checks: a ref is its registered command, an adhoc its argv; once each."""
    reg = registry(cfg)
    out = []
    for c in checks:
        match c:
            case Ref():
                out.append(reg[c.check].cmd if c.check in reg else str(c.check))
            case Adhoc():
                out.append(c.text)
            case _:
                assert_never(c)
    return list(dict.fromkeys(out))


def stage_commands(plan: Plan | None, cfg: EngineConfig) -> list[str]:
    """The commands of every check of the plan's stages (the plan is None before the first plan is accepted)."""
    return commands([c for st in (plan or {}).get("stages") or [] for c in st.get("checks") or []], cfg)


def refusal(check: PlanCheck, cfg: EngineConfig) -> str:
    """Why the registry refuses this plan check ('' when it does not), naming the registered check."""
    reg = registry(cfg)
    match check:
        case Ref():
            return "" if check.check in reg else f"ref `{check.check}`: {_unknown(check.check, reg, cfg)}"
        case Adhoc():
            for r in check.reads:
                if r not in reg:
                    return f"`{clip(check.text, 120)}`: reads `{r}`: {_unknown(r, reg, cfg)}"
            hit = next((k for k in reg.values() if sh.wraps(check.argv, k.argv, JUST_PLAIN_FLAGS)), None)
            if hit is None:
                return ""
            return (f"`{clip(check.text, 120)}`: runs the registered check `{hit.id}` (`{hit.cmd}`) again; the engine already runs it "
                    f"this round on this tree. To require it, write {{kind: ref, check: {hit.id}}}; to assert on its output, write "
                    f"{{kind: adhoc, argv: [a script that reads ${log_var(hit.id)} (its exit code is ${rc_var(hit.id)}) and the "
                    f'variable\'s name], reads: ["{hit.id}"]}}, e.g. ["python3", "tools/assert_log.py", "{log_var(hit.id)}", "passed"]')
        case _:
            assert_never(check)


def _unknown(check_id: CheckId, reg: Mapping[CheckId, CheckSpec], cfg: EngineConfig) -> str:
    if any(k.id == check_id for k in cfg.gate_checks):
        return "that check runs only in the gate at land, never in a stage's round: no plan check names it"
    return f"the repo has no such check (it has: {', '.join(sorted(reg)) or 'none'})"


def refusals(checks: Sequence[PlanCheck], cfg: EngineConfig) -> list[str]:
    """[why] for every plan check the registry refuses."""
    return [why for why in (refusal(c, cfg) for c in checks) if why]
