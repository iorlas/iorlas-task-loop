"""The real round/agent bench with structured check results and check-driven implement admission."""

import hashlib
from dataclasses import replace

from test_checks_round import Checking

from taskloop.admit_chain import ChainAdmission
from taskloop.agents.settings import Overrides, StepSettings
from taskloop.attempt_types import AttemptKey, EntryIdentity
from taskloop.check_repeat.repair import CheckRepeat
from taskloop.check_repeat.store import CheckRepeatStore
from taskloop.checks import argv_digest
from taskloop.command_conclusion import CommandConclusion
from taskloop.evidence_files import EvidenceFiles
from taskloop.git_views import GitProfileFiles
from taskloop.ids import NativeIds
from taskloop.operations import StartPorts, StartRequest
from taskloop.profile import PROFILE_PATH, Profile, read_profile
from taskloop.repeat import StepRepeat
from taskloop.slot_lock import hold, repeating
from taskloop.verifier import Verifier

ASSERTION = "tests/cli/test_check_cli.py: list columns\nE AssertionError: expected Check, got Step\n"


class Repairing(Checking):
    def starting(self) -> StartPorts:
        repair = CheckRepeat(CheckRepeatStore(lambda: self.con), EvidenceFiles(self.tmp), self.tracker.inspect,
                             self.checkouts, self.files, lambda _path: True,
                             lambda path: GitProfileFiles(path, self.checkouts), self, self.observe,
                                 self.command, lambda: self.now, ids=NativeIds())
        verifier = Verifier(self.store, self.checkouts, self.files, lambda _worker: True, lambda: self.now, hold, ids=NativeIds())
        repeat = StepRepeat(self.store, verifier, EvidenceFiles(self.tmp),
                            ChainAdmission(lambda: self.con, self.store.begin, EvidenceFiles(self.tmp),
                                lambda: self.now, ids=NativeIds()), self,
                            lambda _worker: True, self.observe, lambda: self.now, repeating, ids=NativeIds())
        return replace(super().starting(), check_repeat=repair, repeat=repeat)

    def request(self) -> StartRequest:
        return StartRequest(
            "tl-1", "tasks", "/tracker", self.slot.repo.path, StepSettings(), Overrides(model="changed-model", effort="low"), 30
        )

    def conclude(self, key: AttemptKey, body: str, me: EntryIdentity) -> None:
        if body not in ("failed", "passed", "unreleased_failed"):
            return super().conclude(key, body, me)
        files = GitProfileFiles(self.slot.repo.path, self.checkouts)
        commit = self.checks_commit(key)
        profile, blob = read_profile(files, commit), files.blob(commit, PROFILE_PATH)
        assert isinstance(profile, Profile) and isinstance(blob, bytes)
        self.checks.profiled(key, hashlib.sha256(blob).hexdigest())
        block = self.checks.block(key)
        for position, check in enumerate(profile.checks):
            failed = body != "passed" and check.name == "test"
            self.checks.start(key, block, position, check.name, argv_digest(check.argv), check.timeout, self.now)
            self.checks.finish(key, block, position,
                CommandConclusion.FAILED if failed else CommandConclusion.PASSED, 1 if failed else 0, self.now)
            EvidenceFiles(self.tmp).check_log(key, block, check.name).write_text(ASSERTION if failed else "ok\n")
        if body == "unreleased_failed":
            self.checks.conclude(key, "failed", "test:failed", self.now)
        else:
            super().conclude(key, body, me)
