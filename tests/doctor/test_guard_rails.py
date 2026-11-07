"""tl doctor and the guard rails of main (merge-queue.md 8.1): every drift is a FAIL line, an unreadable ruleset is a FAIL, the printed
calls are reads of nothing and writes by nobody."""
import json
from pathlib import Path
from unittest import mock

import pytest
import support.paths  # noqa: F401

# isort: split
from support import procsim

from taskloop.adapters.spawner import RealSpawner
from taskloop.app.doctor import guard_rails as gr
from taskloop.app.doctor.rails import github_slug
from taskloop.contracts.env import snapshot
from taskloop.contracts.procport import Ran

SLUG = "o/r"
GOOD = {"id": 1, "target": "branch", "enforcement": "active", "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"]}}, "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}]}
NOT_PROTECTED = Ran(exit=1, err="gh: Branch not protected (HTTP 404)")


def forge(rulesets: list[dict], protection: Ran = NOT_PROTECTED):
    def read(path: str) -> Ran:
        if path == f"repos/{SLUG}/rulesets":
            return Ran(exit=0, out=json.dumps([{"id": r["id"]} for r in rulesets]))
        if path == f"repos/{SLUG}/branches/main/protection":
            return protection
        one = next((r for r in rulesets if path == f"repos/{SLUG}/rulesets/{r['id']}"), None)
        return Ran(exit=0, out=json.dumps(one)) if one else Ran(exit=1, err="HTTP 404")
    return read


def with_rule(rule: dict, **over) -> dict:
    return {**GOOD, "id": 2, **over, "rules": [*GOOD["rules"], rule]}


def test_the_applied_ruleset_is_clean():
    assert gr.ruleset_findings(forge([GOOD]), SLUG, ["suite"]) == []


@pytest.mark.parametrize("rulesets, words", [
    ([], "no active ruleset"),
    ([{**GOOD, "rules": [{"type": "deletion"}]}], "no active ruleset"),
    ([{**GOOD, "enforcement": "disabled"}], "no active ruleset"),
    ([{**GOOD, "bypass_actors": [{"actor_id": 1}]}], "no active ruleset"),
    ([{**GOOD, "conditions": {"ref_name": {"include": ["refs/heads/other"]}}}], "no active ruleset"),
    ([GOOD, with_rule({"type": "pull_request", "parameters": {}})], "requires a pull request"),
    ([GOOD, with_rule({"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "other"}]}})],
     "requires checks ['other']"),
    ([GOOD, with_rule({"type": "required_status_checks", "parameters": {
        "required_status_checks": [{"context": "suite"}], "strict_required_status_checks_policy": True}})], "up to date"),
])
def test_a_drift_of_the_ruleset_is_a_fail(rulesets, words):
    found = gr.ruleset_findings(forge(rulesets), SLUG, ["suite"])
    assert found and any(words in f for f in found)


def test_a_required_check_that_is_the_profile_check_set_is_not_drift():
    rule = {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "suite"}]}}
    assert gr.ruleset_findings(forge([GOOD, with_rule(rule)]), SLUG, ["suite"]) == []


@pytest.mark.parametrize("protection, words", [
    (Ran(exit=0, out=json.dumps({"required_pull_request_reviews": {}})), "pull request reviews"),
    (Ran(exit=0, out=json.dumps({"required_status_checks": {"contexts": ["x"], "strict": False}})), "requires checks ['x']"),
    (Ran(exit=0, out=json.dumps({"required_status_checks": {"contexts": ["suite"], "strict": True}})), "up to date"),
    (Ran(exit=1, err="HTTP 403: Resource not accessible"), "cannot read"),
])
def test_classic_branch_protection_drift_and_an_unreadable_one_fail(protection, words):
    found = gr.ruleset_findings(forge([GOOD], protection), SLUG, ["suite"])
    assert any(words in f for f in found)


def test_an_unreadable_ruleset_list_fails_and_never_passes():
    found = gr.ruleset_findings(lambda path: Ran(exit=1, err="HTTP 403"), SLUG, ["suite"])
    assert len(found) == 1 and "cannot read" in found[0] and "token scope" in found[0]


def test_a_missing_gh_fails_too():
    def read(path: str) -> Ran:
        raise FileNotFoundError("gh")
    assert "cannot read" in gr.ruleset_findings(read, SLUG, [])[0]


def test_the_hook_missing_stale_or_bypassed_in_one_of_several_worktrees_fails(tmp_path: Path):
    hooks = tmp_path / "githooks"
    hooks.mkdir()
    (hooks / "pre-push").write_text("current")
    seen = [("/w/a", ""), ("/w/b", str(hooks)), ("/w/c", "/elsewhere")]
    assert gr.hook_findings(hooks, "current", seen) == [
        "worktree /w/c sets core.hooksPath to /elsewhere: tl's pre-push judge does not run there"]
    assert "not the current" in gr.hook_findings(hooks, "newer", [])[0]
    (hooks / "pre-push").unlink()
    assert "is missing" in gr.hook_findings(hooks, "current", [])[0]


def test_the_printed_calls_set_the_ruleset_and_name_the_rollback_and_the_full_lock():
    text = gr.print_calls(SLUG)
    assert "gh api -X POST repos/o/r/rulesets" in text and "gh api -X DELETE repos/o/r/rulesets/<id>" in text
    assert '"non_fast_forward"' in text and '"update"' in text


@pytest.mark.parametrize("url, slug", [("git@github.com:o/r.git", "o/r"), ("https://github.com/o/r", "o/r"),
                                       ("git@example.com:o/r.git", ""), ("/local/path", "")])
def test_the_slug_is_a_github_com_origin_or_nothing(url, slug):
    git = mock.Mock()
    git.remote_url.return_value = url
    assert github_slug(git, "/repo") == slug


def test_the_reads_go_through_the_real_adapter_as_gh_api():
    def gh(cwd, env):
        return 0, "[]"
    procsim.fake("gh", gh, args=True)
    spawner = RealSpawner(snapshot())
    found = gr.ruleset_findings(lambda path: spawner.run(["gh", "api", path], timeout_s=5), SLUG, [])
    assert any("no active ruleset" in f for f in found)  # `[]` from gh is a readable, empty list: the ruleset is what is missing
