"""The gate a release runs before it pushes: `just check` (ruff, pyrefly, import-linter), then `just test` (the tests the change can break,
picked by dev/affected.py; tests/rules among them, once), skipped when this exact tree already has a green receipt."""
import os
import shlex
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tlgate import authorization
from tlgate.cache import RunMemo
from tlgate.domain.specs import gate_items
from tlkernel.checks import Check, CheckResult
from tlkernel.config import EngineConfig
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.gitport import Git
from tlkernel.ids import CheckId, TreeSha
from tlkernel.paths import ConfigDir
from tlkernel.runkey import BaseSha, RunKey
from tlkernel.slots import SlotGitError

from tlrelease import suiteout
from tlrelease.host import ReleaseHost
from tlrelease.paths import releases_dir
from tlrelease.shell import Abort, Shell, say


@dataclass(frozen=True)
class GateHost(ReleaseHost):
    """The release flow's additional gate authorization capability."""

    memo_for: Callable[[Git, str, EngineConfig, TreeSha, BaseSha, Env], RunMemo]


LONG = 3 * 3600.0  # a hang guard for a whole gate run


def save_output(out: str, env_dir: Path) -> Path:
    """The full gate output, in the config dir: a file inside the checkout would make the tree dirty and block the release."""
    d = releases_dir(ConfigDir(env_dir))
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"suite-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.log"
    f.write_text(out, encoding="utf-8")
    return f


def red(out: str, what: str, config: Path) -> Abort:
    log = save_output(out, config)
    lines = out.splitlines()
    report = suiteout.failure_report(out) or chr(10).join(lines[-40:])
    return Abort(f"the gate is red ({what}); nothing released:\n{report}\nfull output: {log}",
                 log, suiteout.failing_tests(out))


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


def gate(repo: Path, sh: Shell, host: GateHost) -> None:
    """The repo's one declared gate: the command of the profile's suite check (`just gate`: `just check`, then `just test`, the tests this
    change can break), else `just check` alone. A receipt is written only after this whole command is green, so a hit proves both.
    `just` comes from PATH, else through mise; the config paths mise must trust are exported."""
    if not (repo / "justfile").is_file():  # a bare repo (the tests' fakes) has no gate of its own
        return
    home = os.path.expanduser("~")
    trusted = {"MISE_TRUSTED_CONFIG_PATHS": os.pathsep.join([home + "/.config/mise", home + "/Workspaces"]),
               EnvVar.TL_GREEN_LEDGER.value: ""}  # the release runs every selected test, ledger off
    found = suite_check(repo, sh)
    profile = shlex.split(found[0].cmd) if found else []
    cmd = just(*profile[1:]) if profile[:1] == ["just"] else profile or just("check")
    say("running the gate: " + " ".join(cmd))
    ran = sh.run(cmd, repo, check=False, extra=trusted, timeout_s=LONG)
    if ran.returncode:
        raise red(ran.stdout + ran.stderr, f"`{' '.join(cmd)}` exit {ran.returncode}", host.config_dir(sh.env))
    say("gate green")


@dataclass(frozen=True)
class Receipt:
    """The one receipt of the suite check on the tree at HEAD: its RunKey in the shared result store, the same row `tl check`, `tl gate`
    and the pre-push judge read and write."""

    memo: RunMemo
    check: Check
    key: RunKey

    def hit(self) -> bool:
        return self.memo.hit(self.key) is not None

    def write(self, note: str) -> None:
        self.memo.remember(self.key, CheckResult(id=self.check.id, cmd=self.check.cmd, group=self.check.group, exit=0, status="passed",
                                                 note=note), 0, "")


def receipt(repo: Path, sh: Shell, *, host: GateHost) -> Receipt | None:
    """The receipt the gate on HEAD's tree is known by (None: the repo declares no suite check, so nothing can be remembered)."""
    found = suite_check(repo, sh)
    if found is None:
        return None
    check, cfg = found
    d = str(repo)
    base = BaseSha(sh.port.rev_parse(d, "origin/main"))
    tree = TreeSha(sh.port.rev_parse(d, "HEAD^{tree}"))
    memo = host.memo_for(sh.port, d, cfg, tree, base, sh.env)
    if check.env or check.fix or check.reads:
        raise Abort("release cannot attest a customized suite check; run `tl check` for this registry")
    key = memo.key(check)
    if key is None:
        raise Abort("release suite has no reusable check identity; nothing pushed")
    return Receipt(memo, check, key)


def verify(repo: Path, sh: Shell, checks: Callable[[Path, Shell, GateHost], None] = gate, *, host: GateHost) -> bool:
    """The gate on the tree at `repo`'s HEAD (nothing uncommitted), run once: a green receipt of this tree under this check command (the
    RunKey store, which `tl gate` and the pre-push judge share) skips it, and the log says so (True). A miss says why. Only a green run
    writes a receipt; a red one raises and writes nothing."""
    found = receipt(repo, sh, host=host)
    tree = sh.port.rev_parse(str(repo), "HEAD^{tree}")[:12]
    if found is not None and found.hit():
        say(f"gate receipt hit: tree {tree} already passed `{found.check.cmd}`")
        return True
    say(f"gate receipt miss: no green run of tree {tree} under `{found.check.cmd if found else 'just check'}`")
    checks(repo, sh, host)
    if found is not None:
        found.write("gate verified before the version and manifest bump")
    return False


def record_receipt(repo: Path, sh: Shell, *, host: GateHost) -> None:
    """Publish the verified release bump under the receipt of the bumped tree, so the pre-push judge reuses it."""
    found = receipt(repo, sh, host=host)
    if found is not None:
        found.write("release gate verified before the version and manifest bump")
