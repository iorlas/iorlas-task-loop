"""The gate a release runs before it pushes: `just check` (ruff, pyrefly, import-linter), then `just test` (the tests the change can break,
picked by dev/affected.py; tests/rules among them, once), skipped when this exact tree already passed this exact selection."""
import hashlib
import os
import shlex
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters.ident import config_dir
from taskloop.adapters.suiteout import failing_tests, failure_report
from taskloop.app.checks import authorization
from taskloop.app.release.cache import SuiteCache
from taskloop.app.release.shell import Abort, Shell, say
from taskloop.contracts.checks import Check, CheckResult
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.runkey import BaseSha
from taskloop.contracts.slots import SlotGitError
from taskloop.domain.checks.specs import gate_items
from taskloop.stores.real import real_stores

LONG = 3 * 3600.0  # a hang guard for a whole gate run
AFFECTED = "dev/affected.py"


def save_output(out: str, env_dir: Path) -> Path:
    """The full gate output, in the config dir: a file inside the checkout would make the tree dirty and block the release."""
    d = env_dir / "releases"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"suite-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.log"
    f.write_text(out, encoding="utf-8")
    return f


def red(out: str, what: str, sh: Shell) -> Abort:
    log = save_output(out, config_dir(sh.env))
    lines = out.splitlines()
    return Abort(f"the gate is red ({what}); nothing released:\n{failure_report(out) or chr(10).join(lines[-40:])}\nfull output: {log}",
                 log, failing_tests(out))


def just(*recipe: str) -> list[str]:
    return ["just", *recipe] if shutil.which("just") else ["mise", "exec", "--", "just", *recipe]


def suite_check(repo: Path, sh: Shell) -> tuple[Check, EngineConfig] | None:
    """The repo profile's `suite` check as origin/main has it, with the profile (None: no profile, or no such check). The release runs
    this command and attests this command: nothing in the release names it."""
    d = str(repo)
    try:
        if not sh.port.ls_tree(d, sh.port.rev_parse(d, "origin/main^{tree}"), ".task-loop.json"):
            return None  # an unconfigured repo has no registry evidence for the judge to require
        cfg = authorization.profile(sh.port, d, TreeSha(sh.port.rev_parse(d, "origin/main")))
    except SlotGitError:
        return None  # no origin/main: no profile to read
    found = [c for c in gate_items(cfg) if c.id == CheckId("suite")]
    return (found[0], cfg) if found else None


def gate(repo: Path, sh: Shell) -> None:
    """The repo's own gate: `just check` whenever the repo has a justfile, then the command of the profile's suite check (`just test`:
    the tests this change can break). `just` comes from PATH, else through mise; the config paths mise must trust are exported."""
    if not (repo / "justfile").is_file():  # a bare repo (the tests' fakes) has no gate of its own
        return
    home = os.path.expanduser("~")
    trusted = {"MISE_TRUSTED_CONFIG_PATHS": os.pathsep.join([home + "/.config/mise", home + "/Workspaces"])}
    found = suite_check(repo, sh)
    for cmd in (just("check"), shlex.split(found[0].cmd) if found else []):
        if not cmd:
            continue
        say("running the gate: " + " ".join(cmd))
        ran = sh.run(cmd, repo, check=False, extra=trusted, timeout_s=LONG)
        if ran.returncode:
            raise red(ran.stdout + ran.stderr, f"`{' '.join(cmd)}` exit {ran.returncode}", sh)
    say("gate green")


def selection_digest(repo: Path, sh: Shell) -> str:
    """The hash of the test files `just test` would run on this tree against origin/main ("" when the repo has no selector)."""
    if not (repo / AFFECTED).is_file():
        return ""
    ran = sh.run([sys.executable, AFFECTED, "--base", "origin/main"], repo, check=False)
    return hashlib.sha1(ran.stdout.encode("utf-8")).hexdigest()[:12] if not ran.returncode else ""


def verify(repo: Path, sh: Shell, checks: Callable[[Path, Shell], None] = gate) -> bool:
    """The gate on the tree at `repo`'s HEAD (nothing uncommitted). The same tree under the same command and the same test selection
    passed before: it is skipped, and the log says so (True). Only a green run is remembered; a red one raises and remembers nothing."""
    tree = sh.port.rev_parse(str(repo), "HEAD^{tree}")
    found = suite_check(repo, sh)
    command = f"just check + {found[0].cmd if found else 'no suite check'} selecting " + (selection_digest(repo, sh) or "nothing")
    cache = SuiteCache(ConfigDir(config_dir(sh.env)))
    if cache.hit(tree, command):
        say(f"gate cache hit: tree {tree[:12]} already passed `{command}`")
        return True
    say(f"gate cache miss: no green run of tree {tree[:12]} under `{command}`")
    checks(repo, sh)
    cache.record(tree, command, time.time())
    return False


def record_receipt(repo: Path, sh: Shell) -> None:
    """Publish the verified release bump using the delivery judge's policy, store and complete check key, for the command the gate ran."""
    found = suite_check(repo, sh)
    if found is None:
        return
    check, cfg = found
    d = str(repo)
    base = BaseSha(sh.port.rev_parse(d, "origin/main"))
    tree = TreeSha(sh.port.rev_parse(d, "HEAD^{tree}"))
    memo = authorization.memo_for(real_stores(ConfigDir(config_dir(sh.env))), sh.port, d, cfg, tree, base, sh.env)
    if check.env or check.fix or check.reads:
        raise Abort("release cannot attest a customized suite check; run `tl check` for this registry")
    key = memo.key(check)
    if key is None:
        raise Abort("release suite has no reusable check identity; nothing pushed")
    result = CheckResult(id=check.id, cmd=check.cmd, group=check.group, exit=0, status="passed",
                         note="release gate verified before the version and manifest bump")
    memo.remember(key, result, 0, "")
