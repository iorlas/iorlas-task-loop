"""What the fake git remembers: commits and trees in memory (content-addressed, shared by every repo of a test), refs, HEAD and config
as the small files a real repo keeps them in (so the engine's file-system readers see them change), the working tree as real files."""
import contextlib
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import ignore

Snap = dict[str, bytes]
HEX40 = re.compile(r"[0-9a-f]{40}")


class Fail(Exception):
    """A git command that ends with a message on stderr."""

    def __init__(self, msg: str, rc: int = 1) -> None:
        super().__init__(msg)
        self.msg, self.rc = msg, rc


@dataclass(frozen=True)
class Commit:
    sha: str
    tree: str
    parents: tuple[str, ...]
    msg: str
    seq: int


class World:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.commits: dict[str, Commit] = {}
        self.trees: dict[str, Snap] = {}
        self.index: dict[str, Snap] = {}  # index file path -> staged snapshot
        self.rebases: dict[str, dict] = {}  # git dir -> the rebase in progress
        self.conflicts: dict[str, set[str]] = {}  # git dir -> paths with conflict markers not yet added
        self.prev: dict[str, str] = {}  # git dir -> where HEAD was before its last checkout (what `checkout -` goes back to)
        self.seq = 0


W = World()


def put_tree(snap: Snap) -> str:
    sha = hashlib.sha1(repr(sorted((p, hashlib.sha1(b).hexdigest()) for p, b in snap.items())).encode()).hexdigest()
    W.trees[sha] = dict(snap)
    return sha


def put_commit(snap: Snap, parents: tuple[str, ...], msg: str) -> str:
    W.seq += 1
    tree = put_tree(snap)
    sha = hashlib.sha1(f"{tree} {parents} {msg} {W.seq}".encode()).hexdigest()
    W.commits[sha] = Commit(sha, tree, parents, msg, W.seq)
    return sha


def snap_of(sha: str | None) -> Snap:
    """The files of a commit or a tree ({} for no commit yet)."""
    if sha is None:
        return {}
    return W.trees[W.commits[sha].tree if sha in W.commits else sha]


def ancestors(sha: str) -> set[str]:
    seen, todo = set(), [sha]
    while todo:
        s = todo.pop()
        if s not in seen:
            seen.add(s)
            todo += W.commits[s].parents
    return seen


def walk(include: list[str], exclude: list[str]) -> list[Commit]:
    """The commits reachable from `include` and not from `exclude`, newest first."""
    gone = set().union(*(ancestors(s) for s in exclude)) if exclude else set()
    seen = set().union(*(ancestors(s) for s in include)) - gone if include else set()
    return sorted((W.commits[s] for s in seen), key=lambda c: -c.seq)


def is_ancestor(a: str, b: str) -> bool:
    return a in ancestors(b)


def merge_base(a: str, b: str) -> str | None:
    common = ancestors(a) & ancestors(b)
    return max(common, key=lambda s: W.commits[s].seq) if common else None


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)  # a new inode: the engine's ref memo tells a changed ref by it


class Repo:
    def __init__(self, git: Path, work: Path | None) -> None:
        self.git, self.work = git, work
        self.common = git  # a linked worktree's git dir keeps its own HEAD and index; refs and config live in the common dir
        with contextlib.suppress(OSError):
            self.common = (git / (git / "commondir").read_text(encoding="utf-8").strip()).resolve()

    def base(self, name: str) -> Path:
        return self.git / name if name == "HEAD" else self.common / name

    @property
    def key(self) -> str:
        return str(self.git)

    # -- refs and HEAD ---------------------------------------------------------------------------------------------------------

    def ref(self, name: str) -> str | None:
        try:
            return self.base(name).read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def set_ref(self, name: str, sha: str) -> None:
        atomic_write(self.base(name), sha + "\n")

    def heads(self, prefix: str = "refs/heads") -> dict[str, str]:
        out: dict[str, str] = {}
        root = self.common / prefix
        for p in sorted(root.rglob("*")) if root.is_dir() else []:
            if p.is_file():
                out[str(p.relative_to(root))] = p.read_text(encoding="utf-8").strip()
        return out

    def head_ref(self) -> str:
        """The branch HEAD names ('' when HEAD is detached)."""
        text = self.ref("HEAD") or ""
        return text[len("ref: refs/heads/"):] if text.startswith("ref: refs/heads/") else ""

    def head_sha(self) -> str | None:
        b = self.head_ref()
        return self.ref("refs/heads/" + b) if b else self.ref("HEAD")

    def set_head_branch(self, branch: str) -> None:
        atomic_write(self.git / "HEAD", f"ref: refs/heads/{branch}\n")

    def move_head(self, sha: str) -> None:
        b = self.head_ref()
        if b:
            self.set_ref("refs/heads/" + b, sha)
        else:
            atomic_write(self.git / "HEAD", sha + "\n")

    def head_snap(self) -> Snap:
        return snap_of(self.head_sha())

    # -- config ----------------------------------------------------------------------------------------------------------------

    def config(self) -> dict[str, str]:
        out: dict[str, str] = {}
        sec = ""
        try:
            lines = (self.common / "config").read_text(encoding="utf-8").splitlines()
        except OSError:
            return out
        for ln in lines:
            if m := re.fullmatch(r'\[(\w+)(?: "(.*)")?\]', ln.strip()):
                sec = m.group(1).lower() + ("." + m.group(2) if m.group(2) else "")
            elif "=" in ln:
                k, _, v = ln.partition("=")
                out[f"{sec}.{k.strip().lower()}"] = v.strip()
        return out

    def set_config(self, key: str, value: str) -> None:
        cfg = self.config()
        cfg[key] = value
        groups: dict[str, list[str]] = {}
        for k, v in cfg.items():
            sec, _, name = k.rpartition(".")
            groups.setdefault(sec, []).append(f"\t{name} = {v}")
        head = lambda s: f'[{s.partition(".")[0]} "{s.partition(".")[2]}"]' if "." in s else f"[{s}]"  # noqa: E731
        atomic_write(self.common / "config", "".join(f"{head(s)}\n" + "\n".join(v) + "\n" for s, v in groups.items()))

    # -- names -----------------------------------------------------------------------------------------------------------------

    def resolve(self, expr: str) -> str | None:
        """The sha a revision names: a ref, HEAD, a sha, with ~N and ^ steps, ^{commit} and ^{tree}."""
        tree = expr.endswith("^{tree}")
        expr = expr.removesuffix("^{tree}").removesuffix("^{commit}")
        m = re.fullmatch(r"(.+?)((?:~\d*|\^)*)", expr)
        base, steps = (m.group(1), m.group(2)) if m else (expr, "")
        sha = self._lookup(base)
        for step in re.findall(r"~\d*|\^", steps):
            for _ in range(int(step[1:] or 1) if step[0] == "~" else 1):
                if sha is None or sha not in W.commits or not W.commits[sha].parents:
                    return None
                sha = W.commits[sha].parents[0]
        if sha is not None and tree and sha in W.commits:
            return W.commits[sha].tree
        return sha

    def _lookup(self, name: str) -> str | None:
        if name == "HEAD":
            return self.head_sha()
        if HEX40.fullmatch(name) and (name in W.commits or name in W.trees):
            return name
        for pre in ("", "refs/", "refs/heads/", "refs/remotes/", "refs/tags/"):
            if not name.startswith("-") and self.base(pre + name).is_file():
                return self.ref(pre + name)
        return None

    # -- the working tree ------------------------------------------------------------------------------------------------------

    def scan(self) -> tuple[Snap, list[ignore.Rule]]:
        """Every file of the working tree (not .git) and the ignore rules found in it, shallowest first."""
        assert self.work
        files: Snap = {}
        for d, dirs, names in os.walk(self.work):
            dirs[:] = [x for x in dirs if x != ".git"]
            for n in (x for x in names if x != ".git"):  # a linked worktree has a .git file
                p = Path(d, n)
                if p.is_file() or p.is_symlink():
                    files[p.relative_to(self.work).as_posix()] = p.read_bytes() if p.exists() else b""
        gi = sorted((p for p in files if p == ".gitignore" or p.endswith("/.gitignore")), key=lambda p: p.count("/"))
        rules: list[ignore.Rule] = []
        for p in gi:
            rules += ignore.rules_of(p[: -len(".gitignore")].rstrip("/"), files[p].decode("utf-8", "replace"))
        with contextlib.suppress(OSError):
            rules = ignore.rules_of("", (self.common / "info" / "exclude").read_text(encoding="utf-8")) + rules
        return files, rules

    def read_work(self, path: str) -> bytes | None:
        assert self.work
        try:
            return (self.work / path).read_bytes()
        except OSError:
            return None

    def switch_tree(self, old: Snap, new: Snap) -> None:
        """Make the working tree `new` where it differs from `old`; a file with changes of its own in the way fails the switch."""
        assert self.work
        moving = [p for p in sorted(set(old) | set(new)) if old.get(p) != new.get(p)]
        mine = [p for p in moving if self.read_work(p) not in (None, old.get(p)) and self.read_work(p) != new.get(p)]
        if mine:
            raise Fail("error: Your local changes to the following files would be overwritten by checkout:\n\t" + "\n\t".join(mine))
        for p in moving:
            f = self.work / p
            if p in new:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(new[p])
            elif f.exists():
                f.unlink()
                for parent in f.parents:
                    if parent == self.work or any(parent.iterdir()):
                        break
                    parent.rmdir()


def locate(cwd: str | os.PathLike[str] | None, env: dict[str, str]) -> Repo | None:
    """The repo a git command runs in: GIT_DIR when pinned, else the nearest folder above `cwd` that is a checkout or a bare repo."""
    if env.get("GIT_DIR"):
        wt = env.get("GIT_WORK_TREE")
        return Repo(Path(env["GIT_DIR"]), Path(wt) if wt else None)
    start = Path(cwd or os.getcwd()).resolve()
    for d in (start, *start.parents):
        if (d / ".git").is_dir():
            return Repo(d / ".git", d)
        if (d / ".git").is_file():
            return Repo((d / (d / ".git").read_text(encoding="utf-8").split("gitdir:")[1].strip()).resolve(), d)
        if (d / "HEAD").is_file() and (d / "refs").is_dir():
            return Repo(d, None)
    return None
