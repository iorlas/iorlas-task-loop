"""RunMemo: the repo's one result store, written by every runner (a stage's round, the land gate, a standalone `tl check`). A pass is a
fact about a RunKey (the check and its command and settings, the tree or its `inputs` (and the base unless `inputs_only`), the
selected tests, the toolchain and the env it ran in) and is kept with who made it (run, host, time) and where its output is. Each key
is a DB row of its own, written whole: runners writing at once never lose each other's pass. A failure can come from outside git
(stale build output, a held editor, a flake) and always reruns. A check that may not be cached (`cache: false`, a plan's own command)
has no pass key. The land gate asks the same store as the round: there is no second copy of the decision. A planned `when` skip is
recorded only after a clean round, for its exact tree and base; it is never reused as a pass."""
import hashlib
import json
import os
import platform
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from tlgate.domain import inputs
from tlgate.execution import HOST_IDENTITY, LINUX_IDENTITY
from tlgate.ports import GateStores
from tlkernel import check_files, wire
from tlkernel.checks import BaseRedRecord, Check, CheckResult, PassRecord
from tlkernel.gitport import Git
from tlkernel.ids import CheckId, TreeSha
from tlkernel.runkey import BaseSha, Digest, RunKey

NO_DIGEST = Digest("")


class InputKeys:
    """What the checks of one tree read: its file list is read once, the ignored files under each set of globs once."""

    def __init__(self, git: Git, wt: str | Path, tree: TreeSha, clean: bool = False, pins: Sequence[str] = ()) -> None:
        self.git, self.wt, self.tree = git, str(wt), tree
        self.pins = tuple(pins)  # the profile's pin_files: read by every check's key and by the toolchain digest
        self.clean = clean
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
        return inputs.reads_digest(c, self.tracked() if c.inputs else {}, self.ignored_of(c) if c.inputs else {}, self.pins)

    def toolchain(self, host: str) -> str:
        """The toolchain pins of the tree and the host: what every key of this tree shares."""
        return inputs.toolchain_digest(self.tracked(), host, self.pins)

    def ignored_of(self, c: Check) -> dict[str, str]:
        """{path: content digest} of the gitignored files under the check's globs (tree_hash never sees them)."""
        if self.clean:
            return {}
        at = (tuple(c.inputs), tuple(c.exclude))
        if at not in self.ignored:
            listed = check_files.ignored_files(self.git, self.wt, inputs.pathspec(c.inputs, c.exclude))
            self.ignored[at] = {p: check_files.file_digest(os.path.join(self.wt, p)) for p in inputs.matching(listed, c.inputs, c.exclude)}
        return self.ignored[at]


KEEP = 8  # passes kept per check: the newest by time (a whole-tree check leaves one per tree it passed)


def key_digest(key: RunKey) -> str:
    """The receipt digest: sha1 of the key's fields."""
    fields = wire.dump(key)
    if not key.plan:
        del fields["plan"]  # preserve existing pass keys
    if not key.plan_output:
        del fields["plan_output"]
    return hashlib.sha1(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def plan_digest(cmd: list[str] | None) -> Digest:
    """Exact argv identity; None preserves legacy `when` skips."""
    return Digest(hashlib.sha1(json.dumps(cmd).encode()).hexdigest() if cmd is not None else "")


class RunMemo:
    """The result store of one repo, asked and written for one tree and base. `run_id` and `host` are who writes (the provenance of a
    pass). What this block has run is kept in memory by its complete resolved requirement."""

    def __init__(self, stores: GateStores, repo: str, keys: InputKeys, base: BaseSha, engine_env: Mapping[str, str], run_id: str = "",
                 executor: str = "") -> None:
        self.stores, self.repo, self.keys, self.base, self.engine_env = stores, repo, keys, base, engine_env
        self.run_id, self.host = run_id, platform.node()
        self.executor = executor  # engine.executor.host: where an `in: linux` check ran, part of its key
        self.system = f"{platform.system()}-{platform.machine()}"
        self.ran: dict[RunKey, tuple[CheckResult, float]] = {}  # this block's runs by command -> result, wall limit
        self.slot_keys: InputKeys | None = None
        self.checks: dict[CheckId, Check] = {}
        self.receipts: dict[CheckId, PassRecord] = {}

    def env_of(self, c: Check) -> Digest:
        """The shared receipt environment plus the check's declared env, which can override it."""
        text = json.dumps({**self.engine_env, **c.env}, sort_keys=True)
        return Digest(hashlib.sha1(text.encode("utf-8", "surrogateescape")).hexdigest())

    def key(self, c: Check) -> RunKey | None:
        """The key of a run of this check on this tree; None when it may not be cached, or its `inputs` select nothing (a green over
        changed code would be a wrong hit). A check with `inputs_only` has neither tree nor base in its key: it is true for any base
        and any tree that reads the same inputs."""
        if not c.cache:
            return None
        dependencies = self.dependencies_of(c)
        if dependencies is None:
            return None
        keys = self.slot_keys if c.run_in == "slot" and self.slot_keys is not None else self.keys
        reads = "" if c.inputs and keys.dead(c) else keys.key(c)
        if not reads:
            return None
        whole = not c.inputs
        tree = self.keys.tree if whole else TreeSha("")
        base = self.base if whole or not c.inputs_only else BaseSha("")
        return RunKey(check=c.id, cmd=Digest(inputs.cmd_digest(c)), config=Digest(inputs.config_digest(c)),
                      toolchain=Digest(self.keys.toolchain(self.system)), tree=tree, base=base, inputs=Digest(reads),
                      selected=Digest(inputs.selected_digest(c)), env=self.env_of(c), execution=self.execution(c),
                      dependencies=dependencies)

    def dependencies_of(self, c: Check) -> Digest | None:
        """A reader's inputs include the exact receipts of its producers, never just their command text."""
        records = []
        for ident in c.reads:
            producer = self.checks.get(ident)
            expected = self.key(producer) if producer is not None else None
            hit = self.receipts.get(ident)
            if hit is None:
                hit = self.hit(expected)
            if hit is None or hit.key != expected or hit.result.status != "passed":
                return None
            # A freshly constructed result may carry integer seconds; decoding its receipt normalizes them to floats.
            # Hash the same typed wire form before and after storage, including all producer evidence.
            records.append(wire.dump(wire.load(PassRecord, wire.dump(hit))))
        return Digest(hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()) if records else NO_DIGEST

    def execution(self, c: Check) -> Digest:
        # a pass on one executor says nothing of another, or of this machine
        where = Digest(f"{LINUX_IDENTITY}:{self.executor}") if c.where == "linux" else HOST_IDENTITY
        if c.run_in == "slot":
            return Digest("slot-v1:" + where)
        return Digest("clean-v1:" + where) if self.keys.clean else Digest(where)

    def command_key(self, c: Check) -> RunKey:
        """Only the same registry requirement and resolved execution may share a result."""
        return self.key(c.replace(cache=True)) or self.planned_key(c)

    def planned_key(self, c: Check, plan: Digest = NO_DIGEST, plan_output: Digest = NO_DIGEST) -> RunKey:
        """A plan decision is about this exact diff, even for inputs_only or cache:false checks; never reuse it as a pass."""
        return RunKey(check=c.id, cmd=Digest(inputs.cmd_digest(c)), config=Digest(inputs.config_digest(c)),
                      toolchain=Digest(self.keys.toolchain(self.system)), tree=self.keys.tree, base=self.base,
                      inputs=Digest(inputs.WHOLE_TREE), selected=Digest(inputs.selected_digest(c)), env=self.env_of(c),
                      plan=plan, plan_output=plan_output, execution=self.execution(c))

    def base_key(self, c: Check) -> RunKey:
        """The run of the command on the untouched base: it reads that commit's tree, so no tree and no inputs."""
        return self.command_key(c).replace(tree=TreeSha(""))

    def hit(self, key: RunKey | None) -> PassRecord | None:
        """The remembered green result of this run. Only a pass is ever reused."""
        if key is None:
            return None
        found = self.stores.results(self.repo, key.check).of(key_digest(key)).get()
        return found if (found is not None and found.key == key and found.result.status == "passed"
                         and satisfied(found.result)) else None

    def has(self, c: Check) -> bool:
        """The run this check would make is already a fact (the land gate's whole question)."""
        return self.hit(self.key(c)) is not None

    def result(self, c: Check, plan: Digest = NO_DIGEST) -> CheckResult | None:
        """Authorize only evidence for the entire expected key; historical ID queries are display only."""
        hit = self.hit(self.key(c))
        if hit is not None:
            return hit.result
        docs = self.stores.results(self.repo, c.id)
        for name in docs.keys():  # noqa: SIM118 (a DocSet is not iterable)
            rec = docs.of(name).get()
            if (rec is not None and rec.tree == self.keys.tree and rec.base == self.base
                    and rec.result.planned and satisfied(rec.result)
                    and rec.key == self.planned_key(c, plan, rec.key.plan_output)):
                return rec.result
        return None

    def latest(self, c: Check) -> PassRecord | None:
        """The newest stored receipt of the check made for this tree and base; display only (it names what differs)."""
        docs = self.stores.results(self.repo, c.id)
        names = docs.keys()  # a DocSet is not iterable: it has keys()
        found = [r for n in names if (r := docs.of(n).get()) is not None and r.tree == self.keys.tree and r.base == self.base]
        return max(found, key=lambda r: r.ts, default=None)

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

    def carry_over(self, key: RunKey, found: PassRecord) -> None:
        """A pass of the same check on an earlier base, proven to hold for this key too (app/land/carry.py): stored under this key, its
        `origin` naming the run that really made it."""
        self._put(PassRecord(key=key, result=found.result, tree=self.keys.tree, base=self.base, run_id=self.run_id, host=self.host,
                             ts=time.time(), origin=found.origin or found.run_id, round=found.round, log_abs=found.log_abs))

    def _put(self, rec: PassRecord) -> None:
        self.receipts[rec.key.check] = rec
        docs = self.stores.results(self.repo, rec.key.check)
        docs.of(key_digest(rec.key)).write(rec)
        docs.keep_newest(KEEP)

    def base_was_red(self, c: Check) -> bool | None:
        """True or False when the command has run on this base (by any runner of the repo); None when it has not."""
        rec = self.stores.base_red(self.repo).of(key_digest(self.base_key(c))).get()
        return rec.red if rec is not None else None

    def set_base_red(self, c: Check, red: bool) -> None:
        key = self.base_key(c)
        self.stores.base_red(self.repo).of(key_digest(key)).write(
            BaseRedRecord(key=key, red=red, run_id=self.run_id, host=self.host, ts=time.time()))


def is_green(stores: GateStores, repo: str, step: CheckId, tree: TreeSha, base: BaseSha, plan: Digest | None = NO_DIGEST) -> bool:
    """Historical display query only. Delivery must use RunMemo.result with the resolved requirement."""
    return green_result(stores, repo, step, tree, base, plan) is not None


def satisfied(res: CheckResult) -> bool:
    """Other skips, cancellations and unverified results never satisfy a gate."""
    return not res.cancelled and (res.status == "passed" or (res.status == "skipped" and res.planned))


def green_result(stores: GateStores, repo: str, step: CheckId, tree: TreeSha, base: BaseSha,
                 plan: Digest | None = NO_DIGEST) -> CheckResult | None:
    """Historical display evidence; this ID-only query must never authorize delivery."""
    docs = stores.results(repo, step)
    names = docs.keys()  # a DocSet is not iterable: it has keys()
    for r in (docs.of(n).get() for n in names):
        if (r is not None and r.key.check == step and r.tree == tree and r.base == base and satisfied(r.result)
                and (r.result.status == "passed" or (plan is not None and r.key.plan == plan))):
            return r.result
    return None
