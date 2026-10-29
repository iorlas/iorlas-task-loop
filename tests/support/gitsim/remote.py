"""init, clone, fetch, pull, push: repos made and talked to as plain folders on disk."""
from pathlib import Path

from .ctx import Ctx, flags
from .model import Fail, Repo, W, atomic_write, is_ancestor, locate, snap_of


def make_repo(path: Path, bare: bool, branch: str = "main") -> Repo:
    git = path if bare else path / ".git"
    (git / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    atomic_write(git / "HEAD", f"ref: refs/heads/{branch}\n")
    atomic_write(git / "info" / "exclude", "# git ls-files --others --exclude-from=.git/info/exclude\n")
    repo = Repo(git, None if bare else path)
    repo.set_config("core.bare", "true" if bare else "false")
    return repo


def cmd_init(c: Ctx) -> int:
    args = c.args
    branch = args[args.index("-b") + 1] if "-b" in args else "main"
    dest = [a for a in args if not a.startswith("-") and a != branch][-1:] or ["."]
    make_repo((Path(c.cwd) / dest[0]).resolve(), "--bare" in args, branch)
    return 0


def cmd_clone(c: Ctx) -> int:
    fl, rest = flags(c.args)
    src, dst = rest[0], (Path(c.cwd) / rest[1]).resolve()
    origin = locate(src, {})
    if origin is None:
        raise Fail(f"fatal: repository '{src}' does not exist", 128)
    heads, branch = origin.heads(), origin.head_ref()
    repo = make_repo(dst, "--bare" in fl, branch)
    repo.set_config("remote.origin.url", src)
    for name, sha in heads.items():
        repo.set_ref(("refs/heads/" if "--bare" in fl else "refs/remotes/origin/") + name, sha)
    if "--bare" not in fl and branch in heads:
        repo.set_ref("refs/heads/" + branch, heads[branch])
        repo.set_config(f"branch.{branch}.remote", "origin")
        repo.set_config(f"branch.{branch}.merge", "refs/heads/" + branch)
        repo.switch_tree({}, snap_of(heads[branch]))
        W.index[str(repo.git / "index")] = dict(snap_of(heads[branch]))
    return 0


def remote_of(c: Ctx, name: str) -> Repo:
    url = c.r.config().get(f"remote.{name}.url")
    remote = locate(url, {}) if url else None
    if remote is None:
        raise Fail(f"fatal: '{name}' does not appear to be a git repository", 128)
    return remote


def cmd_fetch(c: Ctx) -> int:
    _, rest = flags(c.args)
    remote = remote_of(c, rest[0] if rest else "origin")
    for name, sha in remote.heads().items():
        c.r.set_ref("refs/remotes/origin/" + name, sha)
    return 0


def cmd_pull(c: Ctx) -> int:
    _, rest = flags(c.args)
    cmd_fetch(Ctx(c.repo, rest[:1], c.env, c.cwd))
    r = c.r
    theirs, mine = r.ref(f"refs/remotes/origin/{rest[1]}"), r.head_sha()
    if theirs is None or mine == theirs or (mine and is_ancestor(theirs, mine)):
        return 0
    if mine and not is_ancestor(mine, theirs):
        raise Fail("fatal: Not possible to fast-forward, aborting.", 128)
    r.switch_tree(snap_of(mine), snap_of(theirs))
    r.move_head(theirs)
    c.set_index(snap_of(theirs))
    return 0


def cmd_push(c: Ctx) -> int:
    fl, rest = flags(c.args)
    remote = remote_of(c, rest[0])
    for spec in rest[1:] or [c.r.head_ref()]:
        forced = spec.startswith("+") or any(f.startswith("--force") for f in fl)
        src, _, dst = spec.lstrip("+").partition(":")
        dst = (dst or src).removeprefix("refs/heads/")
        sha = c.r.resolve(src)
        if sha is None:
            raise Fail(f"error: src refspec {src} does not match any", 1)
        cur = remote.ref("refs/heads/" + dst)
        if cur and not forced and not is_ancestor(cur, sha):
            raise Fail(f" ! [rejected]        {src} -> {dst} (fetch first)\nerror: failed to push some refs to '{remote.git}'", 1)
        remote.set_ref("refs/heads/" + dst, sha)
        c.r.set_ref("refs/remotes/origin/" + dst, sha)
    return 0
