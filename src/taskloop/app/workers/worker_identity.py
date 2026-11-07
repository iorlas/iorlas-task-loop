"""Snapshot the effective request and its execution inputs before calling a worker."""

import hashlib
import json
import stat
from dataclasses import dataclass, replace
from pathlib import Path

from tlkernel.delegate import RunRequest
from tlkernel.gitport import Git
from tlkernel.run import CallIdentity


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def execution_id(identity: CallIdentity) -> str:
    return "execution-v1:" + digest([
        identity.semantics, identity.worktree, identity.cwd, identity.tree,
        identity.cwd_tree, identity.head, identity.cwd_head,
    ])


@dataclass(frozen=True)
class NodeInput:
    node: str
    prompt: str
    schema: object
    request: RunRequest


@dataclass(frozen=True)
class ExecutionContext:
    worktree: str
    cwd: str
    tree: str
    cwd_tree: str
    head: str
    cwd_head: str

    def __post_init__(self) -> None:
        if not all((self.worktree, self.cwd, self.tree, self.cwd_tree, self.head, self.cwd_head)):
            raise ValueError("cannot establish execution identity without cwd, worktree, tree and HEAD")


def context(git: Git, worktree: str, directory: str) -> ExecutionContext:
    wt, cwd = str(Path(worktree).resolve()), str(Path(directory).resolve())
    tree, head = git.tree_of(wt), git.rev_parse(wt, "HEAD")
    if cwd != wt and not git.toplevel(cwd):
        # Picture-only judges run outside a checkout: bind directory contents.
        return ExecutionContext(wt, cwd, tree, directory_tree(Path(cwd)), head, "directory-v1")
    return ExecutionContext(
        wt, cwd, tree, tree if cwd == wt else git.tree_of(cwd),
        head, head if cwd == wt else git.rev_parse(cwd, "HEAD"),
    )


def directory_tree(directory: Path) -> str:
    if not directory.is_dir():
        raise ValueError(f"cannot establish execution identity for {directory}")
    rows = []
    for path in sorted(directory.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            body = str(path.readlink())
        elif stat.S_ISREG(mode):
            with path.open("rb") as stream:
                body = hashlib.file_digest(stream, "sha256").hexdigest()
        elif stat.S_ISDIR(mode):
            body = ""
        else:
            raise ValueError(f"cannot establish execution identity for {path}")
        rows.append((path.relative_to(directory).as_posix(), mode, body))
    return "directory-v1:" + digest(rows)


@dataclass(frozen=True)
class PreparedCall:
    request: RunRequest
    semantics: str
    context: ExecutionContext

    @property
    def snapshot(self) -> CallIdentity:
        c = self.context
        return CallIdentity(
            semantics=self.semantics, worktree=c.worktree, cwd=c.cwd, tree=c.tree,
            cwd_tree=c.cwd_tree, head=c.head, cwd_head=c.cwd_head,
        )

    @property
    def execution_id(self) -> str:
        return execution_id(self.snapshot)

    def at(self, context: ExecutionContext) -> PreparedCall:
        """Bind an in-flight checkpoint to a new context, retaining its request."""
        return replace(self, context=context)


def prepare_call(input: NodeInput, context: ExecutionContext, producer: str) -> PreparedCall:
    r = input.request
    semantics = digest([
        producer, input.node, input.prompt, input.schema, r.role, r.task, r.authored_by,
        r.thread, r.boundary, r.unattended, r.timeout_s, r.idle_s, sorted(r.only_family), sorted(r.engine_only), r.engine_only_advisory,
        r.writer_exec_allow, sorted(r.read_roots), *([r.instructions_ref] if r.instructions_ref else []),
    ])
    return PreparedCall(r, semantics, context)
