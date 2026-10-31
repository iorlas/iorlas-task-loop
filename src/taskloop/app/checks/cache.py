"""RunMemo: the repo's one result store, written by every runner (a stage's round, the land gate, a standalone `tl check`). A pass is a
fact about a RunKey (the check and its command and settings, the tree or its `inputs` (and the base unless `inputs_only`), the
selected tests, the toolchain and the env it ran in) and is kept with who made it (run, host, time) and where its output is. Each key
is a file of its own, written whole: runners writing at once never lose each other's pass. A failure can come from outside git
(stale build output, a held editor, a flake) and always reruns. A check that may not be cached (`cache: false`, a plan's own command)
has no pass key. The land gate asks the same store as the round: there is no second copy of the decision. A planned `when` skip is
recorded only after a clean round, for its exact tree and base; it is never reused as a pass."""
import hashlib
import json
import os
import platform
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from taskloop.adapters import check_files
from taskloop.contracts import wire
from taskloop.contracts.checks import BaseRedRecord, Check, CheckResult, PassRecord
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.ports import Git
from taskloop.contracts.runkey import BaseSha, Digest, RunKey
from taskloop.domain.checks import inputs
from taskloop.domain.checks.names import norm
from taskloop.stores.bundle import Stores


class InputKeys:
    """What the checks of one tree read: its file list is read once, the ignored files under each set of globs once."""

    def __init__(self, git: Git, wt: str | Path, tree: TreeSha) -> None:
        self.git, self.wt, self.tree = git, str(wt), tree
        self.files: dict[str, str] | None = None
        self.ignored: dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, str]] = {}

    def tracked(self) -> dict[str, str]:
        if self.files is None:
            self.files = check_files.tree_files(self.git, self.wt, self.tree)
        return self.files

    def dead(self, c: Check) -> list[str]:
        """The check's `inputs` globs that match no tracked file in the tree."""
        return inputs.dead_globs(self.tracked(), c.inputs)

    def key(self, c: Check) -> str:
        """The digest of what the check reads ('' when its globs select nothing)."""
        return inputs.reads_digest(c, self.tracked() if c.inputs else {}, self.ignored_of(c) if c.inputs else {})

    def toolchain(self, host: str) -> str:
        """The toolchain pins of the tree and the host: what every key of this tree shares."""
        return inputs.toolchain_digest(self.tracked(), host)

    def ignored_of(self, c: Check) -> dict[str, str]:
        """{path: content digest} of the gitignored files under the check's globs (tree_hash never sees them)."""
        at = (tuple(c.inputs), tuple(c.exclude))
        if at not in self.ignored:
            listed = check_files.ignored_files(self.git, self.wt, inputs.pathspec(c.inputs, c.exclude))
            self.ignored[at] = {p: check_files.file_digest(os.path.join(self.wt, p)) for p in inputs.matching(listed, c.inputs, c.exclude)}
        return self.ignored[at]


KEEP = 8  # passes kept per check: the newest by time (a whole-tree check leaves one per tree it passed)


def key_digest(key: RunKey) -> str:
    """The name of a key's file: sha1 of the key's fields."""
    return hashlib.sha1(json.dumps(wire.dump(key), sort_keys=True).encode()).hexdigest()


class RunMemo:
    """The result store of one repo, asked and written for one tree and base. `run_id` and `host` are who writes (the provenance of a
    pass). What this block has run is kept in memory (so a command is never launched twice in it)."""

    def __init__(self, stores: Stores, repo: str, keys: InputKeys, base: BaseSha, engine_env: Mapping[str, str], run_id: str = "") -> None:
        self.stores, self.repo, self.keys, self.base, self.engine_env = stores, repo, keys, base, engine_env
        self.run_id, self.host = run_id, platform.node()
        self.system = f"{platform.system()}-{platform.machine()}"
        self.lock = threading.Lock()  # lanes remember at the same time
        self.ran: dict[RunKey, tuple[CheckResult, float]] = {}  # this block's runs by command -> result, wall limit

    def env_of(self, c: Check) -> Digest:
        """The env a check runs in: what the engine hands every child (the slot's, the registered names) and the check's own."""
        text = json.dumps({**self.engine_env, **c.env}, sort_keys=True)
        return Digest(hashlib.sha1(text.encode("utf-8", "surrogateescape")).hexdigest())

    def key(self, c: Check) -> RunKey | None:
        """The key of a run of this check on this tree; None when it may not be cached, or its `inputs` select nothing (a green over
        changed code would be a wrong hit). A check with `inputs_only` has neither tree nor base in its key: it is true for any base
        and any tree that reads the same inputs."""
        if not c.cache:
            return None
        reads = "" if c.inputs and self.keys.dead(c) else self.keys.key(c)
        if not reads:
            return None
        whole = not c.inputs
        tree = self.keys.tree if whole else TreeSha("")
        base = self.base if whole or not c.inputs_only else BaseSha("")
        return RunKey(check=c.id, cmd=Digest(inputs.cmd_digest(c)), config=Digest(inputs.config_digest(c)),
                      toolchain=Digest(self.keys.toolchain(self.system)), tree=tree, base=base, inputs=Digest(reads),
                      selected=Digest(inputs.selected_digest(c)), env=self.env_of(c))

    def command_key(self, c: Check) -> RunKey:
        """A command is its own identity within a block, whatever id it carries (a plan's copy of a registered command is that run)."""
        return RunKey(check=CheckId(norm(c.cmd)), cmd=Digest(inputs.cmd_digest(c)), config=Digest(""), toolchain=Digest(""),
                      tree=self.keys.tree, base=self.base, inputs=Digest(""), selected=Digest(""), env=self.env_of(c))

    def planned_key(self, c: Check) -> RunKey:
        """A plan decision is about this exact diff, even for inputs_only or cache:false checks; never reuse it as a pass."""
        return RunKey(check=c.id, cmd=Digest(inputs.cmd_digest(c)), config=Digest(inputs.config_digest(c)),
                      toolchain=Digest(self.keys.toolchain(self.system)), tree=self.keys.tree, base=self.base,
                      inputs=Digest(inputs.WHOLE_TREE), selected=Digest(inputs.selected_digest(c)), env=self.env_of(c))

    def base_key(self, c: Check) -> RunKey:
        """The run of the command on the untouched base: it reads that commit's tree, so no tree and no inputs."""
        return self.command_key(c).replace(tree=TreeSha(""))

    def hit(self, key: RunKey | None) -> PassRecord | None:
        """The remembered green result of this run. Only a pass is ever reused."""
        if key is None:
            return None
        found = self.stores.results(self.repo, key.check).of(key_digest(key)).get()
        return found if found is not None and found.key == key and found.result.status == "passed" else None

    def has(self, c: Check) -> bool:
        """The run this check would make is already a fact (the land gate's whole question)."""
        return self.hit(self.key(c)) is not None

    def cached(self, c: Check, hit: PassRecord) -> CheckResult:
        """The remembered result as this round's: cached, with the round it ran in said (and that its log is gone when it is)."""
        note = "inputs unchanged since round %s" % (hit.round or "?") if c.inputs else ""
        if hit.log_abs and not os.path.exists(hit.log_abs):
            note += ("; " if note else "") + "its log has expired"
        return hit.result.replace(id=c.id, cmd=c.cmd, group=c.group, cached=True, log="", note=note, waited=0.0)

    def reuse(self, hit: PassRecord) -> None:
        """A pass served for a tree or base other than the one it was made for (a key without them): never the old record as it was,
        a new one for the current tree and base, from this run, that names the run that made the result."""
        if hit.tree == self.keys.tree and hit.base == self.base:
            return
        self._put(hit.replace(tree=self.keys.tree, base=self.base, run_id=self.run_id, host=self.host, ts=time.time(),
                              origin=hit.origin or hit.run_id))

    def remember(self, key: RunKey, res: CheckResult, rnd: int, log_abs: str) -> None:
        """A pass, or a planned skip committed by a clean round, is a fact. Keep at most KEEP per check."""
        if not satisfied(res):
            return
        self._put(PassRecord(key=key, result=res, tree=self.keys.tree, base=self.base, run_id=self.run_id, host=self.host,
                             ts=time.time(), round=rnd, log_abs=log_abs))

    def _put(self, rec: PassRecord) -> None:
        docs = self.stores.results(self.repo, rec.key.check)
        docs.of(key_digest(rec.key)).write(rec)
        with self.lock:
            names = docs.keys()
            if len(names) > KEEP:
                have = [(r.ts, n) for n in names if (r := docs.of(n).get()) is not None]
                for _, n in sorted(have, reverse=True)[KEEP:]:
                    docs.of(n).delete()

    def base_was_red(self, c: Check) -> bool | None:
        """True or False when the command has run on this base (by any runner of the repo); None when it has not."""
        rec = self.stores.base_red(self.repo).of(key_digest(self.base_key(c))).get()
        return rec.red if rec is not None else None

    def set_base_red(self, c: Check, red: bool) -> None:
        key = self.base_key(c)
        self.stores.base_red(self.repo).of(key_digest(key)).write(
            BaseRedRecord(key=key, red=red, run_id=self.run_id, host=self.host, ts=time.time()))


def repo_green(stores: Stores, git: Git, wt: str, step: CheckId, tree: TreeSha, base: BaseSha) -> bool:
    """is_green for the repo of the worktree `wt`."""
    return is_green(stores, check_files.repo_key(git, wt), step, tree, base)


def repo_green_result(stores: Stores, git: Git, wt: str, step: CheckId, tree: TreeSha, base: BaseSha) -> CheckResult | None:
    """green_result for the repo of the worktree `wt`."""
    return green_result(stores, check_files.repo_key(git, wt), step, tree, base)


def is_green(stores: Stores, repo: str, step: CheckId, tree: TreeSha, base: BaseSha) -> bool:
    """Read-only: a pass or planned skip is recorded for exactly this tree and base."""
    return green_result(stores, repo, step, tree, base) is not None


def satisfied(res: CheckResult) -> bool:
    """Other skips, cancellations and unverified results never satisfy a gate."""
    return not res.cancelled and (res.status == "passed" or (res.status == "skipped" and res.planned))


def green_result(stores: Stores, repo: str, step: CheckId, tree: TreeSha, base: BaseSha) -> CheckResult | None:
    """The same green decision as is_green, with its evidence for the CLI."""
    docs = stores.results(repo, step)
    names = docs.keys()  # a DocSet is not iterable: it has keys()
    for r in (docs.of(n).get() for n in names):
        if r is not None and r.key.check == step and r.tree == tree and r.base == base and satisfied(r.result):
            return r.result
    return None
