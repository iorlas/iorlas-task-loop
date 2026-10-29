"""Plan-check lint: the plan's checks, and which of them can run. Pure; what the tree and the machine say comes in as a TreeProbe."""
import os
from collections.abc import Sequence
from typing import Any

from taskloop.contracts.argv import FORM, argv_of, argv_problems
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ports import TreeProbe
from taskloop.domain.checks import matchers
from taskloop.domain.checks.cmd import matchers as sh
from taskloop.domain.checks.matchers import glob_re
from taskloop.domain.checks.names import log_var, mangle, norm, rc_var
from taskloop.domain.matchers import clip

Plan = Any  # the plan's JSON until E6 types it
JUST_PLAIN_FLAGS = frozenset({"--unstable", "-q", "--quiet", "-v", "--verbose", "--dry-run", "-n", "--no-deps", "--highlight",
                              "--no-highlight"})
GATE_ONLY_TEXT = ("\n\nYour plan was sent back: these checks run a command that runs only in the gate at land (the engine "
                  "runs it once, on the rebased tree), never on a stage's uncommitted tree:\n%s\nRewrite them without "
                  "it: the land gate proves what it proves.")


def plan_checks(plan: Plan) -> list[str]:
    """The plan's checks: stages, risks, cases."""
    return list(dict.fromkeys([c for s in plan.get("stages") or [] for c in s["checks"]] + [
        x["check"] for k in ("risks", "cases") for x in plan.get(k) or []
        if x.get("check", "").strip() and x.get("class", "test") == "test"
        and x.get("proved_by", "check") in ("check", "stage")]))  # a look, taste, leftover or engine-step case has no command


def tracker_checks(plan: Plan) -> list[str]:
    """The plan's checks that read the issue tracker instead of the code (no writer can run bd)."""
    return [c for c in plan_checks(plan) if sh.reads_tracker(argv_of(c))]


GATE_WHY = "the engine runs the gate once, on the rebased tree"


def gate_only(cfg: EngineConfig) -> list[tuple[str, str]]:
    """[(cmd, why)]: the commands only the gate runs: the checks that say run gate."""
    out = [(k.cmd, k.why or GATE_WHY) for k in cfg.checks if k.run == "gate"]
    return [(norm(c), why) for c, why in out if c.strip()]


def rerun_checks(plan: Plan, cfg: EngineConfig) -> list[tuple[str, str]]:
    """[(check, id)]: the plan's checks that contain a configured check's command as a run of whole words."""
    out: list[tuple[str, str]] = []
    for c in plan_checks(plan):
        for k in cfg.stage_checks:
            if sh.contains_argv(argv_of(c), k.argv):
                out.append((c, k.id))
                break
    return out


def gate_only_checks(plan: Plan, cfg: EngineConfig) -> list[tuple[str, str]]:
    """[(check, reason)]: the plan's checks that run a gate-only command."""
    rules = [(c, "{} runs only in the gate at land{}".format(c, ": " + why if why else "")) for c, why in gate_only(cfg)]
    out = []
    for c in plan_checks(plan):
        hit = next((why for cmd, why in rules if sh.runs_command(argv_of(c), argv_of(cmd))), None)
        if hit:
            out.append((c, hit))
    return out


def own_timeout_problems(plan: Plan, cap_min: float) -> list[str]:
    """[why] for a plan check that sets a time limit above the engine's check limit: the engine kills it at the cap, every round
    (lifesim-yxbb.3: a play test with timeout_ms 2400000 under a 30-minute cap timed out five rounds, 2.5 hours)."""
    out: list[str] = []
    for c in plan_checks(plan):
        for minutes, text in sh.own_timeouts(c):
            if minutes > float(cap_min):
                out.append(f"`{clip(c, 120)}`: sets its own limit `{text.strip()}` = {round(minutes, 1):g} min, above the engine's "
                           f"check limit of {float(cap_min):g} min, so the engine kills it at the limit every round: lower the limit, or "
                           "split the work into checks that each finish inside it")
                break
    return out


def repo_check_of(cmd: str, cfg: EngineConfig) -> str | None:
    """The id of the configured check a plan check is, or None."""
    want = norm(cmd)
    return next((k.id for k in cfg.stage_checks if norm(k.cmd) == want), None)


def unity_problems(plan: Plan, cfg: EngineConfig) -> list[str]:
    """[why] for a plan check that runs a `just unity-*` recipe. The repo's checks run it once per round; an acceptance copy launches
    Unity again (lifesim-22b3 r4, yxbb.3: 200 to 540 s each) or, as a wrapper, reads the repo check's log at best."""
    out = []
    for c in plan_checks(plan):
        recipe = sh.just_recipe(argv_of(c), JUST_PLAIN_FLAGS)
        if not recipe.startswith("unity-"):
            continue
        rid = repo_check_of(c, cfg) or next((k.id for k in cfg.stage_checks if k.cmd.split()[-1:] == [recipe]), None)
        use = (f"the repo check `{rid}` already runs it: read ${log_var(rid)} and ${rc_var(rid)}"
               if rid else "it is a Unity run the repo's checks own: do not launch it from acceptance")
        out.append(f"`{clip(c, 120)}`: runs `just {recipe}`; {use}")
    return out


def ledger_problems(plan: Plan) -> list[str]:
    """A case with nothing to prove it: a test case whose proof is `check` (or unsaid) and whose check is empty."""
    return ["case `{}` has no check: give a command, or say in proved_by how it is proved (stage, leftover, "
            "engine_step), or a class of look-objective or taste".format(c["criterion"][:120])
            for c in plan.get("cases") or []
            if c.get("class", "test") == "test" and c.get("proved_by", "check") == "check" and not c.get("check", "").strip()]


def producer_problems(plan: Plan, cfg: EngineConfig) -> list[str]:
    """[why] for a plan check that reads $TL_CHECK_LOG_/RC_<ID> of a repo check whose `when` matches no file any stage lists (it
    never runs, so the variable is never set), or of a check the repo does not have: nothing produces what it reads."""
    files = [f for st in plan.get("stages") or [] for f in st["files"]]
    by_name = {mangle(k.id): k for k in cfg.stage_checks}
    out = []
    for c in plan_checks(plan):
        for name in matchers.env_refs(c):
            k = by_name.get(name)
            if k is None:
                out.append(f"`{clip(c, 120)}`: reads $TL_CHECK_*_{name}, but the repo has no check with that id: nothing produces it")
            elif k.when and not any(glob_re(g).match(f.strip().lstrip("./")) for g in k.when for f in files):
                out.append(f"`{clip(c, 120)}`: reads the output of the repo check `{k.id}`, which runs only for changes under "
                           f"{', '.join(k.when)} and no stage lists a file there, so it will not run: drop the read, or list the files it "
                           "needs in a stage")
    return out


def evidence_problems(plan: Plan, evidence: str) -> list[str]:
    """[why] for a plan check that reads a file in the evidence folder which no check writes (a redirect) and no stage lists: the
    folder holds what a worker saved, and nothing here says one will save that file."""
    if not evidence:
        return []
    prefix = evidence.rstrip("/") + "/"
    made = [f.strip() for st in plan.get("stages") or [] for f in st["files"]]
    out = []
    for c in plan_checks(plan):
        for f in dict.fromkeys(t for t in argv_of(c) if t.startswith(prefix)):
            if f not in made:
                out.append(f"`{clip(c, 120)}`: reads `{f}` from the evidence folder, and no stage lists it: nothing produces it")
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
    for c in plan_checks(plan):
        argv = argv_of(c)
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
