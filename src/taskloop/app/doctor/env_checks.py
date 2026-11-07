"""`tl doctor` environment checks: the tools the loop runs on (bd, uv, python, git identity, mise), TMPDIR and the config folder.
A finding says what is wrong and the command that fixes it. Reads only; the one process it starts is `<tool> --version`."""
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from tlkernel.bd_errors import BdCommandFailure
from tlkernel.beadsport import BdFailure
from tlkernel.procport import Ran

MIN_PYTHON: Final = (3, 15)
SHARED_TMP: Final = ("/tmp", "/var/tmp")
PROBE_S: Final = 10.0


class Runner(Protocol):
    """The part of the process port the checks use."""

    def run(self, argv: list[str], *, cwd: str | None = None, timeout_s: float | None = None) -> Ran: ...


class Configs(Protocol):
    """The part of the git port the checks use."""

    def config_get(self, d: str, key: str) -> str: ...


@dataclass(frozen=True)
class Finding:
    level: str  # FAIL | WARN
    text: str
    fix: str

    def line(self) -> str:
        return f"{self.level} {self.text}; fix: {self.fix}"


def bd_builds(path: str) -> list[Path]:
    """Every distinct `bd` executable on `path`, first on PATH first (two links to one build count once)."""
    seen: dict[Path, Path] = {}
    for folder in path.split(os.pathsep):
        found = Path(folder) / "bd" if folder else None
        if found is not None and found.is_file() and os.access(found, os.X_OK):
            seen.setdefault(found.resolve(), found)
    return list(seen.values())


def version_of(text: str) -> str:
    """The first dotted number in a tool's `--version` output ('bd version 1.3.1 (abc)' -> '1.3.1'); '' when there is none."""
    words = (w.strip("v,()") for w in text.split())
    return next((w for w in words if w[:1].isdigit()), "")


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split(".") if p.isdigit())


def why_it_failed(text: str) -> str:
    """': <the tool's first line>' (cut at 120 characters), or '' when it said nothing."""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return f": {first[:120]}" if first else ""


def bd_fix(build: Path, said: str) -> str:
    """A mise shim that refuses because the folder's mise.toml is not trusted is cured by `mise trust`; any other bd is reinstalled."""
    if "mise" in said and "not trusted" in said:
        return "run `mise trust` in this folder (mise will not run a shim under a mise.toml it has not been told to trust)"
    return f"remove {build} from PATH or reinstall it"


def bd_findings(path: str, run: Runner, opens: Callable[[], object], repo: str) -> list[Finding]:
    """bd on PATH is one build, it runs, and it opens the repo's database (`opens` is a read-only list)."""
    builds = bd_builds(path)
    if not builds:
        return [Finding("FAIL", "bd is not on PATH", "`mise install` (bd is pinned in mise.toml) and put its folder on PATH")]
    out: list[Finding] = []
    versions: dict[Path, str] = {}
    for build in builds:
        try:
            ran = run.run([str(build), "--version"], timeout_s=PROBE_S)
        except OSError as err:
            out.append(Finding("FAIL", f"bd at {build} cannot start ({err})", f"remove {build} from PATH or reinstall it"))
            continue
        if ran.exit != 0:
            out.append(Finding("FAIL", f"bd at {build} does not run (exit {ran.exit}){why_it_failed(ran.err or ran.out)}",
                               bd_fix(build, ran.err + ran.out)))
            continue
        versions[build] = version_of(ran.out + ran.err)
    newest = max(versions, key=lambda b: version_key(versions[b]), default=None)
    if len(set(versions.values())) > 1 and newest is not None:
        listing = ", ".join(f"{b} {v or '?'}" for b, v in versions.items())
        out.append(Finding(
            "FAIL", f"{len(builds)} different bd builds on PATH ({listing}); the first one runs, and it cannot open a database a newer "
                    "build wrote ('table has unknown fields')",
            f"remove the others from PATH, or put the newest first: export PATH={newest.parent}:$PATH"))
    try:
        opens()
    except (BdFailure, BdCommandFailure, OSError, SystemExit) as err:
        first = builds[0]
        out.append(Finding("FAIL", f"bd {versions.get(first) or '?'} at {first} cannot open the database of {repo}: {err}",
                           f"run `bd doctor` in {repo}; the build that wrote the database is the one to use"
                           + (f" ({newest} is the newest on PATH)" if newest is not None and newest != first else "")))
    return out


def tool_findings(path: str, python: tuple[int, ...], run: Runner, git: Configs, repo: str) -> list[Finding]:
    """uv and Python 3.15 resolve, git has an identity, mise has every tool mise.toml pins."""
    out: list[Finding] = []
    if shutil.which("uv", path=path) is None:
        out.append(Finding("FAIL", "uv is not on PATH", "`mise install` (uv is pinned in mise.toml) and put its folder on PATH"))
    if python[:2] < MIN_PYTHON:
        out.append(Finding("FAIL", f"tl runs on Python {'.'.join(map(str, python[:3]))}; {'.'.join(map(str, MIN_PYTHON))}+ is required",
                           "`uv python install 3.15`, then run tl through `uv run --script`"))
    missing = [k for k in ("user.name", "user.email") if not git.config_get(repo, k)]
    if missing:
        out.append(Finding("WARN", f"git has no {' and '.join(missing)}: commits and merges fail or carry a wrong author",
                           "`git config --global user.name NAME` and `git config --global user.email EMAIL`"))
    if shutil.which("mise", path=path) is None:
        out.append(Finding("WARN", "mise is not on PATH: the pinned dev tools (just, ruff, pyrefly) are not checked", "install mise"))
    else:
        try:
            ran = run.run(["mise", "ls", "--missing"], cwd=repo, timeout_s=PROBE_S)
        except OSError:
            return out
        if ran.exit == 0 and ran.out.strip():
            first = ran.out.strip().splitlines()[0].split()
            out.append(Finding("WARN", f"mise tools pinned in mise.toml are not installed ({first[0] if first else '?'} first)",
                               "`mise install`"))
    return out


def folder_findings(tmpdir: str, config: Path) -> list[Finding]:
    """TMPDIR is a folder of this session's own (not the shared /tmp) and writable; the config folder is writable."""
    out: list[Finding] = []
    if not tmpdir or tmpdir.rstrip("/") in SHARED_TMP:
        out.append(Finding("WARN", f"TMPDIR is {tmpdir or 'unset'}: scratch files of parallel sessions share one folder",
                           "export TMPDIR=$HOME/tmp (a folder of this session's own) before starting the session"))
    elif not (Path(tmpdir).is_dir() and os.access(tmpdir, os.W_OK)):
        out.append(Finding("FAIL", f"TMPDIR {tmpdir} is not a writable folder", f"mkdir -p {tmpdir}"))
    target = config if config.exists() else config.parent
    if not os.access(target, os.W_OK):
        out.append(Finding("FAIL", f"the config folder {config} is not writable", f"chmod u+w {target}"))
    return out


def all_findings(path: str, tmpdir: str, config: Path, python: tuple[int, ...], run: Runner, git: Configs, opens: Callable[[], object],
                 repo: str) -> list[Finding]:
    return bd_findings(path, run, opens, repo) + tool_findings(path, python, run, git, repo) + folder_findings(tmpdir, config)
