"""The stdlib pre-push client forwards git's complete request to the application delivery judge. Only exit zero authorizes a push;
an unavailable or erroring judge refuses. No profile, evidence, or delivery policy is interpreted in this plain-python3 process."""
# git-port-exempt: plain python3 in git's own hook path; it imports no port and no record (tests/hook/test_hook.py)
from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path


def entry(argv: list[str], stdin_text: str, environ: Mapping[str, str]) -> int:
    """argv: the tl command, then git's own (remote name, url). Forward stdin unchanged; only the judge's exit zero lets it go."""
    try:
        if not argv:
            raise ValueError("delivery judge command is missing")
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False, timeout=15)
        if top.returncode or not top.stdout.strip():
            raise ValueError("cannot locate the repository")
        result = subprocess.run([argv[0], "judge-push", "--repo", top.stdout.strip()], input=stdin_text,
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


def githook(name: str, argv: list[str], stdin_text: str, environ: Mapping[str, str]) -> int:
    """argv: the tl command, then git's own arguments for the hook. tl's logic first (pre-push), then the repo's own hook of this name
    with the same arguments and stdin; the first failure's exit code. A repo that uses LFS and has no pre-push hook of its own still
    gets `git lfs pre-push`: a plain `git push` never skips its LFS objects."""
    if not argv:
        return 1 if name == "pre-push" else 0
    tl, args = argv[0], argv[1:]
    if name == "pre-push" and (rc := entry([tl, *args], stdin_text, environ)):
        return rc
    try:
        mine = Path(original_hooks_dir(tl, environ)) / name
        cmd = [str(mine), *args] if mine.is_file() and os_executable(mine) else (
            ["git", "lfs", "pre-push", *args] if name == "pre-push" and uses_lfs() else [])
        if not cmd:
            return 0
        # the repo's pre-push hook never runs the gate: a `tl judge-push` it calls only reads the receipt (TL_JUDGE_READ_ONLY)
        child = {**environ, "TL_JUDGE_READ_ONLY": "1"} if name == "pre-push" else None
        return subprocess.run(cmd, input=stdin_text if name in STDIN_HOOKS else None, text=True, check=False, env=child).returncode
    except Exception as err:
        if name == "pre-push":
            print(f"tl pre-push: refused: chained hook unavailable: {err}", file=sys.stderr)
            return 1
        return 0


def os_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)
