"""The stdlib pre-push client forwards git's complete request to the application delivery judge. Only exit zero authorizes a push;
an unavailable or erroring judge refuses. No profile, evidence, or delivery policy is interpreted in this plain-python3 process."""
# git-port-exempt: plain python3 in git's own hook path; it imports no port and no record (tests/hook/test_hook.py)
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

JUDGE_TL = "TL_JUDGE_TL"  # contracts/envvars.py: the tl.py of the install that started this engine child (adapters/childenv.hooks_vars)


def judge_command(tl: str, environ: Mapping[str, str]) -> list[str]:
    """The command that judges a push: the engine's own install when it named one (an engine on install X is judged by X, whatever the
    shim points at now), else the shim `tl` the hook was written with (a push by hand)."""
    own = environ.get(JUDGE_TL, "")
    return [shutil.which("uv") or "uv", "run", "--quiet", "--script", own] if own and Path(own).is_file() else [tl]


def entry(argv: list[str], stdin_text: str, environ: Mapping[str, str]) -> int:
    """argv: the tl command, then git's own (remote name, url). Forward stdin unchanged; only the judge's exit zero lets it go."""
    try:
        if not argv:
            raise ValueError("delivery judge command is missing")
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False, timeout=15)
        if top.returncode or not top.stdout.strip():
            raise ValueError("cannot locate the repository")
        result = subprocess.run([*judge_command(argv[0], environ), "judge-push", "--repo", top.stdout.strip()], input=stdin_text,
                                text=True, check=False, timeout=3600)
        if result.returncode == 0:
            return 0
        print("tl pre-push: refused: delivery judge refused or is unavailable", file=sys.stderr)
    except Exception as err:
        print(f"tl pre-push: refused: delivery judge unavailable: {err}", file=sys.stderr)
    return 1


# The hooks tl's dir answers (git reads core.hooksPath for all of them). Each runs tl's logic where it has any (pre-push), then the
# repo's own hook of the same name, so nothing the repo installed (git-lfs's shim, prek) is skipped by the hooks path tl sets.
STDIN_HOOKS = frozenset({"pre-push", "post-rewrite"})  # git feeds these on stdin (pre-push: the refs); the others get the terminal's


def original_hooks_dir(tl: str, environ: Mapping[str, str]) -> str:
    """The folder the repo's own hooks live in: its core.hooksPath as configured (read without the GIT_CONFIG_* tl injected), else
    <common git dir>/hooks."""
    clean = {k: v for k, v in environ.items() if not k.startswith("GIT_CONFIG_")}
    configured = subprocess.run(["git", "config", "--get", "core.hooksPath"], capture_output=True, text=True, check=False, env=clean)
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, check=False, env=clean)
    where = configured.stdout.strip() or (str(Path(common.stdout.strip()) / "hooks") if common.stdout.strip() else "")
    mine = Path(tl).resolve().parent.parent / "githooks"
    return "" if not where or Path(where).resolve() == mine else where


def uses_lfs() -> bool:
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False).stdout.strip()
    try:
        return bool(top) and "filter=lfs" in (Path(top) / ".gitattributes").read_text(encoding="utf-8")
    except OSError:
        return False


def ours(tl: str) -> bool:
    """One rule: tl judges a push only in a repo registered with it (the `repos` row of factory.db, in the config dir `tl` lives in, keyed
    by the main checkout; a worktree or slot of it counts). Any other repo (a test's tmp repo, a clone tl never saw) is not tl's to judge.
    A registry that cannot be read says yes: the judge decides, never a silent skip."""
    db = Path(tl).resolve().parent.parent / "factory.db"
    try:
        if not db.is_file():
            return False
        con = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT v FROM repos_doc WHERE k = 'repos'").fetchone()
        finally:
            con.close()
        if row is None:
            return False
        known = {os.path.realpath(e["path"]) for e in json.loads(row[0])["repos"].values()}
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True,
                                check=False, timeout=15).stdout.strip()
        if Path(common).name == ".git":
            return os.path.realpath(Path(common).parent) in known
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False, timeout=15)
        return os.path.realpath(top.stdout.strip()) in known
    except Exception:
        return True


def without_hooks_path(environ: Mapping[str, str]) -> dict[str, str]:
    """`environ` minus tl's injected core.hooksPath (GIT_CONFIG_COUNT/KEY_n/VALUE_n; other entries keep their order): the repo's own hook
    and whatever it runs (a test suite that pushes in its own tmp repos) must not inherit tl's hooks dir."""
    try:
        count = int(environ.get("GIT_CONFIG_COUNT") or 0)
    except ValueError:
        return dict(environ)
    keep = [(environ[f"GIT_CONFIG_KEY_{i}"], environ[f"GIT_CONFIG_VALUE_{i}"]) for i in range(count)
            if f"GIT_CONFIG_KEY_{i}" in environ and environ[f"GIT_CONFIG_KEY_{i}"].lower() != "core.hookspath"]
    out = {k: v for k, v in environ.items() if not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    if "GIT_CONFIG_COUNT" in out:
        out["GIT_CONFIG_COUNT"] = str(len(keep))
    for i, (key, value) in enumerate(keep):
        out[f"GIT_CONFIG_KEY_{i}"], out[f"GIT_CONFIG_VALUE_{i}"] = key, value
    return out


def githook(name: str, argv: list[str], stdin_text: str, environ: Mapping[str, str]) -> int:
    """argv: the tl command, then git's own arguments for the hook. tl's logic first (pre-push), then the repo's own hook of this name
    with the same arguments and stdin; the first failure's exit code. A repo that uses LFS and has no pre-push hook of its own still
    gets `git lfs pre-push`: a plain `git push` never skips its LFS objects."""
    if not argv:
        return 1 if name == "pre-push" else 0
    tl, args = argv[0], argv[1:]
    if name == "pre-push" and ours(tl) and (rc := entry([tl, *args], stdin_text, environ)):
        return rc
    try:
        mine = Path(original_hooks_dir(tl, environ)) / name
        cmd = [str(mine), *args] if mine.is_file() and os_executable(mine) else (
            ["git", "lfs", "pre-push", *args] if name == "pre-push" and uses_lfs() else [])
        if not cmd:
            return 0
        return subprocess.run(cmd, input=stdin_text if name in STDIN_HOOKS else None, text=True, check=False,
                              env=without_hooks_path(environ)).returncode
    except Exception as err:
        if name == "pre-push":
            print(f"tl pre-push: refused: chained hook unavailable: {err}", file=sys.stderr)
            return 1
        return 0


def os_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)
