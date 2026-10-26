"""Plan-check lint: the plan's checks, and which of them can run (moved unchanged from engine.py, E1)."""
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from checks import speed
from core.fmt import clip
from core.procs import child_env

# a check that runs bd or reads the beads files proves the tracker, not the code: no writer can satisfy it (writers cannot
# run bd), so it burns every round (lifesim-fld.26.12, lifesim-fld.27.9: 3 rounds, 2 replans, 89 min, stuck)
TRACKER_CHECK = re.compile(r"(?:^|[;&|(`!{]|\b(?:then|do|else|xargs|exec|command|env|time)\b)\s*bd(?=\s|$|[;&|)`])|"
                           r"(?<![\w-])\.beads\b")


def plan_checks(plan):
    """The plan's checks: stages, risks, cases."""
    return list(dict.fromkeys([c for s in plan.get("stages") or [] for c in s["checks"]] + [
        x["check"] for k in ("risks", "cases") for x in plan.get(k) or []
        if x.get("check", "").strip() and x.get("class", "test") == "test"
        and x.get("proved_by", "check") in ("check", "stage")]))  # a look, taste, leftover or engine-step case has no command


def tracker_checks(plan):
    """The plan's checks that read the issue tracker instead of the code."""
    return [c for c in plan_checks(plan) if TRACKER_CHECK.search(c)]


# a command the repo runs only in the gate (the gate itself, engine.gate_only) is red by design on the uncommitted tree a
# writer leaves, so a check running it burns every round (lifesim-fld.27.9: `just unity-check`, 68 min, stuck)
CMD_LEAD = r"(?:^|[;&|(`!{]|\b(?:then|do|else|xargs|exec|command|env|time)\b)\s*"
GATE_ONLY_TEXT = ("\n\nYour plan was sent back: these checks run a command that runs only in the gate at land (the engine "
                  "runs it once, on the rebased tree), never on a stage's uncommitted tree:\n%s\nRewrite them without "
                  "it: the land gate proves what it proves.")


def gate_only(cfg):
    """[(cmd, why)]: the gate command and engine.gate_only's entries ("cmd" or {cmd, why})."""
    out = [(cfg.get("gate") or "", "the engine runs the gate once, on the rebased tree")]
    out += [(x, "") if isinstance(x, str) else (x.get("cmd") or "", x.get("why") or "") for x in cfg.get("gate_only") or []]
    return [(" ".join(c.split()), why) for c, why in out if c.strip()]


def rerun_checks(plan, cfg):
    """[(check, id)]: the plan's checks that contain a configured check's command as a whole word."""
    out = []
    for c in plan_checks(plan):
        for k in cfg.get("checks") or []:
            words = (k.get("cmd") or "").split()
            if words and re.search(r"(?<![\w-])" + r"\s+".join(map(re.escape, words)) + r"(?![\w-])", c):
                out.append((c, k.get("id") or k["cmd"]))
                break
    return out


def check_env_name(check_id):
    return "TL_CHECK_LOG_" + re.sub(r"\W+", "_", check_id).upper()


def gate_only_checks(plan, cfg):
    """[(check, reason)]: the plan's checks that run a gate-only command."""
    rules = [(re.compile(CMD_LEAD + r"\s+".join(map(re.escape, c.split())) + r"(?=\s|$|[;&|)`])"),
              "%s runs only in the gate at land%s" % (c, ": " + why if why else "")) for c, why in gate_only(cfg)]
    out = []
    for c in plan_checks(plan):
        hit = next((why for rx, why in rules if rx.search(c)), None)
        if hit:
            out.append((c, hit))
    return out


# a check that cannot run is found before any write, not by a writer's round (tl-bxk.10.13). Conservative on purpose: a false
# alarm costs a planner call, the thing this saves.
PROC_SUBST = re.compile(r"<\(")
FILE_ARG = re.compile(r"(?:^|[;&|(]\s*)(?:test|\[)\s+-[fesr]\s+(\S+)|(?:^|[;&|(]\s*)(?:cat|bash|sh|node|python3?)\s+(?:-[^\smc]\S*\s+)*([^\s;&|<>$`'\"-]*[./]\S*)")


# python3 -I -m unittest tools.tests.test_x / python3 -I -m tools.x: -I (isolated mode) drops the cwd from sys.path, ModuleNotFoundError
ISOLATED_MODULE = re.compile(r"\bpython3?(?:\.\d+)?\s+(?:-[A-Za-z]+\s+)*-[A-Za-z]*I[A-Za-z]*\s+(?:-[A-Za-z]+\s+)*-m\s+(?:unittest\s+(?!discover\b)"
                             r"(?:-[A-Za-z]+\s+)*)?([A-Za-z_][\w]*(?:\.[\w]+)+)")


SHELL_STOP = {"if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac", "{", "}", "(", ")",
              "[[", "]]", "function", "select", "time", "!"}
COMMAND_SEP = {"|", "||", "&&", ";", "&", "|&"}
_WORDS = {}   # (cwd, word) -> resolves; one bash per new word
_RECIPES = {}  # cwd -> (justfile mtime, the recipe and alias names or None)


def shell_tokens(cmd):
    """cmd split like a shell, operators (`;`, `&&`, `|`, `>`) apart; [] when the quoting does not close."""
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = "#"
    try:
        return list(lex)
    except ValueError:
        return []


def first_words(cmd):
    """The command words of a plan check's simple commands: the first word of each command between `;`, `&&`, `||`, `|`,
    after env assignments, `!` and `time`. Stops at a compound command (if, for, a subshell, $(...)): nothing is claimed
    past it."""
    out, start = [], True
    if re.search(r"<<|\(\)\s*\{|\bfunction\s+\w|\bsource\b|^\s*\.\s", cmd):  # a heredoc, a function, a sourced file: not judged
        return []
    for t in shell_tokens(cmd):
        if re.fullmatch(r"[;&|]+", t):
            start = True
            continue
        if not start:
            continue
        if re.fullmatch(r"\w+=.*", t) or t in ("!", "time", "command", "exec", "env", "builtin") or t.startswith("-"):
            continue
        if t in SHELL_STOP or re.search(r"[$`(){}<>]|^\[", t) or re.fullmatch(r"[<>(){}]+", t):
            return out
        out.append(t)
        start = False
    return out


def command_problems(cmd, wt, made=()):
    """[why a plan check cannot start]: a command word that is no builtin, not on PATH and no file of the tree (lifesim-fld.10
    planned 'After building the current player: python3 ...', a sentence run as the command `After`); a `just` recipe the
    tree's justfile does not have (lifesim-ov3w). Conservative: only a plain word is judged. No bash (Windows): nothing."""
    bash = shutil.which("bash")
    if not bash or os.name == "nt":
        return []
    out, words = [], first_words(cmd)
    for n, w in enumerate(words):
        if "/" in w:
            if n or w.startswith("~") or re.search(r"\bcd\b", cmd):
                continue  # a path after another command or a cd may be made by it, or be relative to elsewhere
            if not w.startswith(("./", "/")) and not Path(wt, w.split("/")[0]).is_dir():
                continue  # `.venv/bin/python`: its folder is not in the tree (a setup makes it)
            f = Path(w) if w.startswith("/") else Path(wt, w)
            g = os.path.normpath(w)
            if not f.exists() and not any(g == k or g.startswith(k + "/") for k in map(os.path.normpath, made)):
                out.append("`%s` is not a file of this tree and no stage lists it in files" % w)
            continue
        key = (str(wt), w)
        if key not in _WORDS or time.time() - _WORDS[key][1] > 120:  # a tool installed since is found within two minutes
            r = subprocess.run([bash, "-c", 'type -t -- "$1" >/dev/null 2>&1', "_", w], capture_output=True, env=child_env(), cwd=str(wt))
            _WORDS[key] = (r.returncode == 0, time.time())
        if not _WORDS[key][0]:
            out.append("`%s` is not a command here (no builtin, nothing on PATH): a check is a shell command, never a sentence" % w)
    if "just" in words and not any(Path(f).name.lower() in ("justfile", ".justfile") for f in made):
        toks = shell_tokens(cmd)
        recipes = just_recipes(wt)
        for k, t in enumerate(toks):
            if t == "just" and (k == 0 or re.fullmatch(r"[;&|]+", toks[k - 1])):
                after = toks[k + 1:k + 8]
                if any(x.startswith("-") and x not in JUST_PLAIN_FLAGS for x in after):
                    continue  # an option that takes a value (--justfile, --set, -d): not judged
                rest = [x for x in after if not x.startswith("-")]
                if recipes is not None and rest and re.fullmatch(r"[\w-]+", rest[0]) and rest[0] not in recipes:
                    out.append("`just %s`: the tree's justfile has no recipe %s (it has: %s)" % (
                        rest[0], rest[0], ", ".join(sorted(recipes)[:12]) or "none"))
    return out


JUST_PLAIN_FLAGS = {"--unstable", "-q", "--quiet", "-v", "--verbose", "--dry-run", "-n", "--no-deps", "--highlight", "--no-highlight"}


def just_recipes(wt):
    """The recipe and alias names of the tree's justfile (`just --dump --dump-format json`), private ones too; None when there is
    no just or no justfile here. Cached by the justfile's modification time: a rebase or an edit shows."""
    jf = next((Path(wt, n) for n in ("justfile", "Justfile", ".justfile") if Path(wt, n).is_file()), None)
    if not jf:
        return None
    stamp = jf.stat().st_mtime_ns
    got = _RECIPES.get(str(wt))
    if got and got[0] == stamp:
        return got[1]
    names = None
    try:
        r = subprocess.run(["just", "--dump", "--dump-format", "json"], capture_output=True, text=True, cwd=str(wt), timeout=20, env=child_env())
        if r.returncode == 0:
            d = json.loads(r.stdout)
            names = set((d.get("recipes") or {})) | set((d.get("aliases") or {}))
    except (OSError, subprocess.SubprocessError, ValueError):
        names = None
    _RECIPES[str(wt)] = (stamp, names)
    return names


TIMEOUT_MS = re.compile(r"timeout[_-]?ms\s*[=: ]\s*(\d+)", re.I)
TIMEOUT_MIN = re.compile(r"timeout[_-]?min(?:ute)?s?\s*[=: ]\s*(\d+(?:\.\d+)?)", re.I)
TIMEOUT_SEC = re.compile(r"timeout[_-]?sec(?:ond)?s?\s*[=: ]\s*(\d+(?:\.\d+)?)", re.I)
TIMEOUT_ANY = re.compile(r"(?<![\w-])(?:--timeout|-timeout|timeout)(?:=|\s+)(\d+(?:\.\d+)?)([smhd]?)(?![\w.])", re.I)


def own_timeouts(check):
    """[(minutes, the text)]: the time limits a check sets for itself: `timeout_ms 2400000`, `--timeout=40m`, `timeout 2400 cmd`,
    `-timeout_min 40`. A bare number is seconds."""
    out = []
    for m in TIMEOUT_MS.finditer(check):
        out.append((float(m.group(1)) / 60000.0, m.group(0)))
    for m in TIMEOUT_MIN.finditer(check):
        out.append((float(m.group(1)), m.group(0)))
    for m in TIMEOUT_SEC.finditer(check):
        out.append((float(m.group(1)) / 60.0, m.group(0)))
    for m in TIMEOUT_ANY.finditer(check):
        out.append((float(m.group(1)) * {"": 1 / 60.0, "s": 1 / 60.0, "m": 1.0, "h": 60.0, "d": 1440.0}[m.group(2).lower()], m.group(0)))
    return out


def timeout_problems(plan, cap_min):
    """tl-btt: [why] for a plan check that sets a time limit above the engine's check limit: the engine kills it at the cap, every
    round (lifesim-yxbb.3: a play test with timeout_ms 2400000 under a 30-minute cap timed out five rounds, 2.5 hours)."""
    out = []
    for c in plan_checks(plan):
        for minutes, text in own_timeouts(c):
            if minutes > float(cap_min):
                out.append("`%s`: sets its own limit `%s` = %g min, above the engine's check limit of %g min, so the engine kills it at the "
                           "limit every round: lower the limit, or split the work into checks that each finish inside it" % (
                               clip(c, 120), text.strip(), round(minutes, 1), float(cap_min)))
                break
    return out


UNITY_RECIPE = re.compile(r"(?<![\w-])just\s+(unity-[\w-]+)(?![\w-])")


def repo_check_of(cmd, cfg):
    """The id of the configured check a plan check is, wrappers aside (`mkdir -p e && just unity-tests > e/log` is `unity-tests`), or None."""
    want = speed.canon(cmd)
    return next((k.get("id") or k["cmd"] for k in cfg.get("checks") or [] if speed.canon(k.get("cmd") or "") == want), None)


def unity_problems(plan, cfg):
    """tl-7y6.7.7: [why] for a plan check that runs a `just unity-*` recipe. The repo's checks run it once per round; an acceptance
    copy launches Unity again (lifesim-22b3 r4, yxbb.3: 200 to 540 s each) or, as a wrapper, reads the repo check's log at best."""
    out = []
    for c in plan_checks(plan):
        bare = re.sub(r"\"[^\"]*\"|'[^']*'", "''", c)  # a quoted mention is text
        m = UNITY_RECIPE.search(bare)
        if not m:
            continue
        rid = repo_check_of(c, cfg) or next((k.get("id") for k in cfg.get("checks") or [] if (k.get("cmd") or "").split()[-1:] == [m.group(1)]), None)
        use = ("the repo check `%s` already runs it: read $%s and $%s" % (rid, check_env_name(rid), check_env_name(rid).replace("_LOG_", "_RC_"))
               if rid else "it is a Unity run the repo's checks own: do not launch it from acceptance")
        out.append("`%s`: runs `just %s`; %s" % (clip(c, 120), m.group(1), use))
    return out


def ledger_problems(plan):
    """tl-bxk.13.16.1: a case with nothing to prove it: a test case whose proof is `check` (or unsaid) and whose check is empty."""
    out = []
    for c in plan.get("cases") or []:
        if c.get("class", "test") == "test" and c.get("proved_by", "check") == "check" and not c.get("check", "").strip():
            out.append("case `%s` has no check: give a command, or say in proved_by how it is proved (stage, leftover, "
                       "engine_step), or a class of look-objective or taste" % c["criterion"][:120])
    return out


def dry_check(plan, wt):
    """[error]: the plan's checks that cannot run: bash -n syntax, process substitution, a file the check reads that is
    neither in the tree nor a file some stage names."""
    errs, made = [], [os.path.normpath(f) for st in plan.get("stages") or [] for f in st["files"]]
    for c in plan_checks(plan):
        bare = re.sub(r"\"[^\"]*\"|'[^']*'", "''", c)
        if PROC_SUBST.search(bare):
            errs.append("`%s`: process substitution `<(` is not allowed (write the output to a file instead)" % c)
        try:
            r = subprocess.run(["bash", "-n"], input=c, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            r = None
        if r is not None and r.returncode:
            errs.append("`%s`: bash -n: %s" % (c, (r.stderr or "syntax error").strip().splitlines()[-1][:200]))
            continue
        for w in command_problems(c, wt, made):  # tl-bxk.13.16.2
            errs.append("`%s`: %s" % (c, w))
        iso = ISOLATED_MODULE.search(bare)
        if iso and Path(wt, iso.group(1).split(".")[0]).is_dir():  # tl-bxk.13.13
            errs.append("`%s`: python -I removes the working directory from the import path, so `%s` cannot be imported; "
                        "drop -I, or run `python3 -I -m unittest discover -s <dir> -p <pattern>` (a path, not a module name)" % (
                            c, iso.group(1)))
            continue
        if re.search(r"(?:^|[;&|(\s])cd\s", c):
            continue
        for m in FILE_ARG.finditer(c):
            f = (m.group(1) or m.group(2) or "").strip("\"'")
            g = os.path.normpath(f)
            if (not f or re.search(r"[$*?{}~`]", f) or f.startswith("/") or "://" in f
                    or re.search(r">\s*%s(?![\w./-])" % re.escape(f), c) or Path(wt, f).exists()
                    or any(g == k or g.startswith(k + "/") or g.endswith("/" + k) for k in made)):
                continue
            errs.append("`%s`: `%s` is not in the tree and no stage lists it in files (add it to the stage that creates it)" % (c, f))
    return list(dict.fromkeys(errs))
