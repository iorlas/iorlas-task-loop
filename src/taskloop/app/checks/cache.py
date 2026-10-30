"""RunMemo: the one memo of check runs. A pass is a fact about a RunKey (the check, the tree or its `inputs`, the base, the env it
ran in); a failure can come from outside git (stale build output, a held editor, a flake) and always reruns. A check that may not
be cached (`cache: false`, a plan's own command) has no key, so nothing is ever remembered about it. The land gate asks the same
memo (`has`) the round does (`hit`): there is no second copy of the decision."""
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

from taskloop.adapters import check_files
from taskloop.contracts.checks import BaseEntry, CacheHit, Check, CheckCacheEntry, CheckResult, RunEntry
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.runkey import BaseSha, Digest, RunKey
from taskloop.domain.checks import inputs
from taskloop.domain.checks.names import norm
from taskloop.stores.api import Doc


class InputKeys:
    """What the checks of one tree read: its file list is read once, the ignored files under each set of globs once."""

    def __init__(self, wt: str | Path, tree: TreeSha, env: Mapping[str, str]) -> None:
        self.wt, self.tree, self.env = str(wt), tree, env
        self.files: dict[str, str] | None = None
        self.ignored: dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, str]] = {}

    def tracked(self) -> dict[str, str]:
        if self.files is None:
            self.files = check_files.tree_files(self.wt, self.tree, self.env)
        return self.files

    def dead(self, c: Check) -> list[str]:
        """The check's `inputs` globs that match no tracked file in the tree."""
        return inputs.dead_globs(self.tracked(), c.inputs)

    def key(self, c: Check) -> str:
        """The digest of what the check reads ('' when its globs select nothing)."""
        return inputs.reads_digest(c, self.tracked() if c.inputs else {}, self.ignored_of(c) if c.inputs else {})

    def ignored_of(self, c: Check) -> dict[str, str]:
        """{path: content digest} of the gitignored files under the check's globs (tree_hash never sees them)."""
        at = (tuple(c.inputs), tuple(c.exclude))
        if at not in self.ignored:
            listed = check_files.ignored_files(self.wt, inputs.pathspec(c.inputs, c.exclude), self.env)
            self.ignored[at] = {p: check_files.file_digest(os.path.join(self.wt, p)) for p in inputs.matching(listed, c.inputs, c.exclude)}
        return self.ignored[at]


class RunMemo:
    """check-cache/<bead>.json for one tree and base: the green runs (one per check, the latest), whether a check was red on the
    base, and what this block has run (so a command is never launched twice in it)."""

    def __init__(self, doc: Doc[CheckCacheEntry], keys: InputKeys, base: BaseSha, engine_env: Mapping[str, str]) -> None:
        self.doc, self.keys, self.base, self.engine_env = doc, keys, base, engine_env
        was = doc.get() or CheckCacheEntry()
        self.runs = {e.key: e.hit for e in was.runs}
        self.base_red = {e.key: e.red for e in was.base}
        self.ran: dict[RunKey, tuple[CheckResult, float]] = {}  # this block's runs by command -> result, wall limit

    def env_of(self, c: Check) -> Digest:
        """The env a check runs in: what the engine hands every child (the slot's, the registered names) and the check's own."""
        text = json.dumps({**self.engine_env, **c.env}, sort_keys=True)
        return Digest(hashlib.sha1(text.encode("utf-8", "surrogateescape")).hexdigest())

    def key(self, c: Check) -> RunKey | None:
        """The key of a run of this check on this tree; None when it may not be cached, or its `inputs` select nothing (a green over
        changed code would be a wrong hit)."""
        if not c.cache:
            return None
        reads = "" if c.inputs and self.keys.dead(c) else self.keys.key(c)
        if not reads:
            return None
        whole = not c.inputs
        tree = self.keys.tree if whole else TreeSha("")
        base = self.base if whole or not c.inputs_only else BaseSha("")
        return RunKey(check=c.id, tree=tree, base=base, inputs=Digest(reads), env=self.env_of(c))

    def command_key(self, c: Check) -> RunKey:
        """A command is its own identity within a block, whatever id it carries (a plan's copy of a registered command is that run)."""
        return RunKey(check=CheckId(norm(c.cmd)), tree=self.keys.tree, base=self.base,
                      inputs=Digest(hashlib.sha1(norm(c.cmd).encode("utf-8", "surrogateescape")).hexdigest()), env=self.env_of(c))

    def base_key(self, c: Check) -> RunKey:
        """The run of the command on the untouched base: it reads that commit's tree, so no tree and no inputs."""
        return self.command_key(c).replace(tree=TreeSha(""))

    def hit(self, key: RunKey | None) -> CacheHit | None:
        """The remembered green result of this run. Only a pass is ever reused."""
        found = self.runs.get(key) if key else None
        return found if found is not None and found.result.status == "passed" else None

    def has(self, c: Check) -> bool:
        """The run this check would make is already a fact (the land gate's whole question)."""
        return self.hit(self.key(c)) is not None

    def cached(self, c: Check, hit: CacheHit) -> CheckResult:
        """The remembered result as this round's: cached, with the round it ran in said."""
        note = "inputs unchanged since round %s" % (hit.round or "?") if c.inputs else ""
        return hit.result.replace(id=c.id, cmd=c.cmd, group=c.group, cached=True, log="", note=note, waited=0.0)

    def remember(self, key: RunKey, res: CheckResult, rnd: int, log_abs: str) -> None:
        """Only a pass is a fact; one entry per check, the latest."""
        if res.status != "passed":
            return
        self.runs = {k: v for k, v in self.runs.items() if k.check != key.check}
        self.runs[key] = CacheHit(result=res, round=rnd, log_abs=log_abs)

    def base_was_red(self, c: Check) -> bool | None:
        """True or False when the command has run on this base; None when it has not."""
        return self.base_red.get(self.base_key(c))

    def set_base_red(self, c: Check, red: bool) -> None:
        self.base_red[self.base_key(c)] = red

    def save(self) -> None:
        """Written back with only this tree's and base's entries (a key that reads its `inputs` has no tree to go stale)."""
        tree = self.keys.tree
        self.doc.write(CheckCacheEntry(
            runs=[RunEntry(key=k, hit=v) for k, v in self.runs.items() if not k.tree or (k.tree == tree and k.base == self.base)],
            base=[BaseEntry(key=k, red=v) for k, v in self.base_red.items() if k.base == self.base]))
