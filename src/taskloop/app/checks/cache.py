"""CheckCache: the green results a round may reuse. A pass is a fact about the tree and base (or about a check's own `inputs`);
a failure can come from outside git (stale build output, a held editor, a flake) and always reruns."""
import dataclasses
import os
from collections.abc import Mapping
from pathlib import Path

from taskloop.adapters import check_files
from taskloop.contracts.checks import CacheHit, Check, CheckCacheEntry, CheckResult
from taskloop.domain.checks import inputs
from taskloop.domain.checks.names import norm
from taskloop.stores.api import Doc


class InputKeys:
    """The cache keys of one tree: its file list is read once, the ignored files under each set of globs once."""

    def __init__(self, wt: str | Path, tree: str, base: str, env: Mapping[str, str]) -> None:
        self.wt, self.tree, self.base, self.env = str(wt), tree, base, env
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
        if not c.inputs:
            return ""
        return inputs.input_key(c, self.tracked(), self.ignored_of(c), self.base)

    def ignored_of(self, c: Check) -> dict[str, str]:
        """{path: content digest} of the gitignored files under the check's globs (tree_hash never sees them)."""
        at = (tuple(c.inputs), tuple(c.exclude))
        if at not in self.ignored:
            listed = check_files.ignored_files(self.wt, inputs.pathspec(c.inputs, c.exclude), self.env)
            self.ignored[at] = {p: check_files.file_digest(os.path.join(self.wt, p)) for p in inputs.matching(listed, c.inputs, c.exclude)}
        return self.ignored[at]


class CheckCache:
    """check-cache/<bead>.json, kept for the latest tree only (`whole`) and for every check's inputs (`inputs`, one entry per command)."""

    def __init__(self, doc: Doc[CheckCacheEntry], key: str) -> None:
        self.doc, self.key = doc, key
        was = doc.read() or CheckCacheEntry()
        self.whole = dict(was.whole) if was.key == key else {}
        self.inputs = dict(was.inputs)
        self.base_red = dict(was.base_red)

    def hit(self, c: Check, ikey: str) -> CacheHit | None:
        """The remembered green result for this check, by its inputs' key when it has one, else by the whole tree and base."""
        if c.inputs:
            return self.inputs.get(ikey) if ikey else None
        return self.whole.get(c.cmd)

    def cached(self, c: Check, hit: CacheHit, ikey: str) -> CheckResult:
        """The remembered result as this round's: cached, with the round it ran in said."""
        note = "inputs unchanged since round %s" % (hit.round or "?") if ikey else ""
        return dataclasses.replace(hit.result, id=c.id, cmd=c.cmd, group=c.group, cached=True, log="", note=note)

    def remember(self, c: Check, res: CheckResult, rnd: int, log_abs: str, ikey: str) -> None:
        """Only a pass is a fact about the tree."""
        hit = CacheHit(result=res, round=rnd, log_abs=log_abs)
        if ikey:  # one entry per check
            self.inputs = {k: v for k, v in self.inputs.items() if v.result.cmd != c.cmd}
            self.inputs[ikey] = hit
        else:
            self.whole[c.cmd] = hit

    def base_was_red(self, base: str, cmd: str) -> bool | None:
        """True or False when the command has run on that base; None when it has not."""
        return self.base_red.get(f"{base} {norm(cmd)}")

    def set_base_red(self, base: str, cmd: str, red: bool) -> None:
        self.base_red[f"{base} {norm(cmd)}"] = red

    def green_ids(self, checks: list[Check], keys: InputKeys) -> list[str]:
        """Ids of the repo checks with a green result on this tree: by their inputs hash, else by tree and base."""
        out = []
        for c in checks:
            if not c.cache:
                continue
            ok = not keys.dead(c) and bool(self.inputs.get(keys.key(c) or "-")) if c.inputs else c.cmd in self.whole
            if ok:
                out.append(c.id)
        return out

    def save(self, base: str) -> None:
        """Written back with only the latest tree's entries; base-red answers of other bases are dropped."""
        keep = {k: v for k, v in self.base_red.items() if k.startswith(base + " ")}
        self.doc.write(CheckCacheEntry(key=self.key, whole=self.whole, inputs=self.inputs, base_red=keep))
