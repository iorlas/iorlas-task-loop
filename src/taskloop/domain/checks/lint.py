"""Plan-check lint: the plan's checks, and which of them can run. Pure; what the tree and the machine say comes in as a TreeProbe."""
import os
import shlex
from collections.abc import Sequence
from typing import Final

from taskloop.contracts.argv import FORM, argv_problems
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.plancheck import Adhoc
from taskloop.contracts.ports import TreeProbe
from taskloop.domain.checks.cmd import matchers as sh
from taskloop.domain.checks.names import norm
from taskloop.domain.checks.planref import JUST_PLAIN_FLAGS, Plan, adhocs, plan_checks
from taskloop.domain.matchers import clip

GATE_ONLY_TEXT: Final = ("\n\nYour plan was sent back: these checks run a command that runs only in the gate at land (the engine "
                  "runs it once, on the rebased tree), never on a stage's uncommitted tree:\n%s\nRewrite them without "
                  "it: the land gate proves what it proves.")


def own_checks(plan: Plan) -> list[Adhoc]:
    """The plan's own commands (the refs are registered checks, linted where they are registered)."""
    return adhocs(plan_checks(plan))


def tracker_checks(plan: Plan) -> list[str]:
    """The plan's checks that read the issue tracker instead of the code (no writer can run bd)."""
    return [c.text for c in own_checks(plan) if sh.reads_tracker(c.argv)]


GATE_WHY: Final = "the engine runs the gate once, on the rebased tree"


def gate_only(cfg: EngineConfig) -> list[tuple[str, str]]:
    """[(cmd, why)]: the commands only the gate runs: the checks that say run gate."""
    out = [(k.cmd, k.why or GATE_WHY) for k in cfg.checks if k.run == "gate"]
    return [(norm(c), why) for c, why in out if c.strip()]


def gate_only_checks(plan: Plan, cfg: EngineConfig) -> list[tuple[str, str]]:
    """[(check, reason)]: the plan's checks that run a gate-only command."""
    rules = [(c, "{} runs only in the gate at land{}".format(c, ": " + why if why else "")) for c, why in gate_only(cfg)]
    out = []
    for c in own_checks(plan):
        hit = next((why for cmd, why in rules if sh.runs_command(c.argv, shlex.split(cmd))), None)
        if hit:
            out.append((c.text, hit))
    return out


def own_timeout_problems(plan: Plan, cap_min: float) -> list[str]:
    """[why] for a plan check that sets a time limit above the engine's check limit: the engine kills it at the cap, every round
    (lifesim-yxbb.3: a play test with timeout_ms 2400000 under a 30-minute cap timed out five rounds, 2.5 hours)."""
    out: list[str] = []
    for c in own_checks(plan):
        for minutes, text in sh.own_timeouts(c.text):
            if minutes > float(cap_min):
                out.append(f"`{clip(c.text, 120)}`: sets its own limit `{text.strip()}` = {round(minutes, 1):g} min, above the engine's "
                           f"check limit of {float(cap_min):g} min, so the engine kills it at the limit every round: lower the limit, or "
                           "split the work into checks that each finish inside it")
                break
    return out


def ledger_problems(plan: Plan) -> list[str]:
    """A case with nothing to prove it: a test case whose proof is `check` (or unsaid) and whose check is empty."""
    return ["case `{}` has no check: give a command, or say in proved_by how it is proved (stage, leftover, "
            "engine_step), or a class of look-objective or taste".format(c["criterion"][:120])
            for c in plan.get("cases") or []
            if c.get("class", "test") == "test" and c.get("proved_by", "check") == "check" and not c.get("check")]


def evidence_problems(plan: Plan, evidence: str) -> list[str]:
    """[why] for a plan check that reads a file in the evidence folder which no check writes (a redirect) and no stage lists: the
    folder holds what a worker saved, and nothing here says one will save that file."""
    if not evidence:
        return []
    prefix = evidence.rstrip("/") + "/"
    made = [f.strip() for st in plan.get("stages") or [] for f in st["files"]]
    out = []
    for c in own_checks(plan):
        for f in dict.fromkeys(t for t in c.argv if t.startswith(prefix)):
            if f not in made:
                out.append(f"`{clip(c.text, 120)}`: reads `{f}` from the evidence folder, and no stage lists it: nothing produces it")
    return out


def command_problems(argv: Sequence[str], probe: TreeProbe, made: Sequence[str] = ()) -> list[str]:
    """[why a plan check cannot start]: a program that is no file of the tree and not on PATH (lifesim-fld.10 planned 'After building
    the current player: python3 ...', a sentence run as the command `After`); a `just` recipe the tree's justfile does not have
    (lifesim-ov3w). Only the program word is judged."""
    out: list[str] = []
    for w in dict.fromkeys([argv[0], *sh.head(argv)[:1]]):
        if "/" in w:
            out += _path_problem(w, probe, made)
        elif not probe.has_command(w):
            out.append(f"`{w}` is not an executable here (nothing on PATH): the first word of a check is a program, never a sentence")
    if "just" in sh.head(argv)[:1] and not any(os.path.basename(f).lower() in ("justfile", ".justfile") for f in made):
        name = sh.just_recipe(argv, JUST_PLAIN_FLAGS)
        recipes = probe.recipes()
        if name and recipes is not None and name not in recipes:
            have = ", ".join(sorted(recipes)[:12]) or "none"
            out.append(f"`just {name}`: the tree's justfile has no recipe {name} (it has: {have})")
    return out


def _path_problem(w: str, probe: TreeProbe, made: Sequence[str]) -> list[str]:
    if w.startswith("~"):
        return []  # no shell expands it: judged by nobody
    if not w.startswith(("./", "/")) and not probe.is_dir(w.split("/", maxsplit=1)[0]):
        return []  # `.venv/bin/python`: its folder is not in the tree (a setup makes it)
    g = os.path.normpath(w)
    if probe.exists(w) or any(g == k or g.startswith(k + "/") for k in map(os.path.normpath, made)):
        return []
    return [f"`{w}` is not a file of this tree and no stage lists it in files"]


def dry_check(plan: Plan, probe: TreeProbe) -> list[str]:
    """[error]: the plan's checks that cannot run: a shell string in disguise, a program that does not resolve, a file the check
    reads that is neither in the tree nor a file some stage names."""
    errs: list[str] = []
    made = [os.path.normpath(f) for st in plan.get("stages") or [] for f in st["files"]]
    for a in own_checks(plan):
        argv, c = list(a.argv), a.text
        if not argv:
            errs.append(f"an empty check: {FORM}")
            continue
        if argv_problems(argv):
            errs += [f"`{c}`: {w}" for w in argv_problems(argv)]
            continue
        errs += [f"`{c}`: {w}" for w in command_problems(argv, probe, made)]
        iso = sh.isolated_module(argv)
        if iso and probe.is_dir(iso.split(".")[0]):
            errs.append(f"`{c}`: python -I removes the working directory from the import path, so `{iso}` cannot be imported; drop -I, "
                        "or run `python3 -I -m unittest discover -s <dir> -p <pattern>` (a path, not a module name)")
            continue
        errs += [f"`{c}`: `{f}` is not in the tree and no stage lists it in files (add it to the stage that creates it)"
                 for f in sh.file_operands(argv) if _missing(f, probe, made)]
    return list(dict.fromkeys(errs))


def _missing(f: str, probe: TreeProbe, made: Sequence[str]) -> bool:
    g = os.path.normpath(f)
    return (sh.is_plain_path(f) and not probe.exists(f)
            and not any(g == k or g.startswith(k + "/") or g.endswith("/" + k) for k in made))
