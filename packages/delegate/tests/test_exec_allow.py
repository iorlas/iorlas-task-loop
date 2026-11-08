"""R9-04: the host allow is an argv gate, never a shell or executable prefix rule."""

import contextlib
import io
import json
import sys
from pathlib import Path
from unittest import mock

import hermetic  # noqa: F401
from test_route import route

from delegate.app import env
from delegate.app.codex_policy import worktree_head
from delegate.domain.policy.shell import read_only_problem
from tltestkit.case import Case

ESCAPES = (
    "sed 'e id' f",
    "sed '1e id' f",
    "sed 's/x/id/e' f",
    "sed -f script f",
    "sed --file=script f",
    "sed -n 'w out' f",
    "sed 's/x/y/w out' f",
    "sed --expression='e id' f",
    "sort --compress-program=sh f",
    "sort --compress-prog=sh f",
    "sort -o out f",
    "sort --output=out f",
    "git grep -Osh x",
    "git grep --open-files-in-pager=sh x",
    "git --paginate log",
    "git log --ext-diff",
    "git diff --textconv",
    "git diff --no-index a b --output=out",
    "git -c core.pager=sh log",
    "rg --pre=sh x",
    "rg --hostname-bin=sh x",
    "find . -execdir sh {} +",
    "find . -fprintf out x",
    "jq --run-tests f",
    "jq --raw-output 'debug' f > out",
    "diff --output=out a b",
    "env cat f",
    "xargs cat",
    "nice cat f",
    "timeout 1 cat f",
    "nohup cat f",
    "uv run cat f",
    "npx cat f",
    "make check",
    "just -f other check",
    "cat f & touch out",
    "cat <(touch out)",
)
WRAPPERS = ("env", "sh", "bash", "zsh", "xargs", "nice", "timeout", "nohup", "uv", "npx", "make", "sudo", "command", "exec")


class ExecAllow(Case):
    def setup_method(self):
        self.root = env.config_dir()
        self.host = self.root / "host.json"
        self.doc = {
            "binaries": {"python": sys.executable, "uv": "/opt/pinned/uv", "dotnet": "/opt/pinned/dotnet", "just": "/opt/pinned/just"},
            "writer_exec_allow": [
                ["dotnet", "build"],
                ["dotnet", "test"],
                ["dotnet", "restore"],
                ["dotnet", "--version"],
                ["python", "-m", "unittest"],
                ["python", "-m", "pytest"],
                ["python", "-I", "-B", "-m", "unittest"],
                ["python", "-I", "-B", "-m", "pytest"],
                ["uv", "run", "--no-sync", "--project", ".", "python", "-m", "pytest"],
                ["just", "check"],
            ],
        }
        self.save()

    def save(self):
        self.host.write_text(json.dumps(self.doc))

    def call(self, argv, *flags, spawn=None, exit_code=0):
        """-> (exit code, the posix_spawnp mock the guard starts the command with, stderr); the child is never really started."""
        err = io.StringIO()
        with (
            contextlib.redirect_stderr(err),
            mock.patch("delegate.app.codex_policy.os.posix_spawnp", spawn or mock.Mock(return_value=4242)) as run,
            mock.patch("delegate.app.codex_policy.os.waitpid", return_value=(4242, exit_code << 8)),
            mock.patch("delegate.app.codex_policy.worktree_head", return_value="abc123"),
        ):
            code = route.main(["guard", *flags, "--exec-allow", *argv])
        return code, run, err.getvalue()

    def rows(self):
        """The authorization rows; the `exit` row a started command leaves after it ends is read with `exits`."""
        return [r for r in self.all_rows() if r["mode"] != "exit"]

    def exits(self):
        return [r for r in self.all_rows() if r["mode"] == "exit"]

    def all_rows(self):
        return [json.loads(line) for line in (self.root / "guard.jsonl").read_text().splitlines()]

    def test_decided_broad_forms_use_only_pinned_absolute_binaries(self):
        for argv in (
            ["dotnet", "build", "x.csproj", "-p:Foo=bar"],
            ["dotnet", "test", "--filter", "Name=x"],
            ["dotnet", "restore", "x.csproj"],
            ["dotnet", "--version"],
            ["python", "-m", "pytest", "-q", "tests"],
            ["python", "-I", "-B", "-m", "pytest", "-q", "tests"],
            ["python", "-I", "-B", "-m", "unittest", "discover"],
            ["uv", "run", "--no-sync", "--project", ".", "python", "-m", "pytest", "-q"],
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            ["just", "check"],
        ):
            with self.subTest(argv=argv):
                code, run, _ = self.call(argv)
                assert code == 0
                want = self.doc["binaries"].get(argv[0], argv[0])
                assert run.call_args.args[1] == [want, *argv[1:]]  # an argv list, never a shell line
        assert len(self.rows()) == 10
        assert all(r["allowed"] for r in self.rows())
        assert len(self.exits()) == 10

    def test_denial_corpus_never_starts_a_child_and_audits_once(self):
        denied = [
            ["dotnet-evil", "test"],
            ["/tmp/dotnet", "test"],
            ["dotnet", "test-evil"],
            ["dotnet", "exec", "payload"],
            ["dotnet", "--version", "extra"],
            ["python", "-c", "pass"],
            ["python", "-m", "pytest.evil"],
            ["python", "-I", "-m", "pytest"],
            ["python", "-B", "-m", "pytest"],
            ["python", "-I", "-B", "-c", "pass"],
            ["uv", "run", "python", "-m", "pytest"],
            ["uv", "run", "--no-sync", "--project", "/x", "python", "-m", "pytest"],
            ["uv", "run", "--no-sync", "--project", ".", "python", "-c", "pass"],
            ["uv", "run", "--no-sync", "--project", ".", "pytest"],
            ["just", "check", "evil"],
            ["just", "-f", "other", "check"],
            ["just", "--justfile=other", "check"],
            ["just", "--", "check"],
            [],
            ["dotnet", "test", "\0"],
            ["sed", "e id"],
            ["sort", "--compress-program=sh"],
            ["git", "grep", "-Osh", "x"],
        ]
        denied += [[w, "dotnet", "test"] for w in WRAPPERS]
        for argv in denied:
            with self.subTest(argv=argv):
                code, run, why = self.call(argv)
                assert code == 2, why
                run.assert_not_called()
        rows = self.rows()
        assert len(rows) == len(denied)
        assert all(not r["allowed"] and r["reason"] for r in rows)

    def test_read_steps_and_engine_only_recipes_cannot_get_the_allow(self):
        for argv, flags in ((["dotnet", "test"], ["--read-only"]), (["just", "check"], ["--engine-only=check"])):
            code, run, _ = self.call(argv, *flags)
            assert code == 2
            run.assert_not_called()

    def test_missing_unreadable_malformed_or_invalid_host_refuses(self):
        for bad in (
            None,
            "{",
            "[]",
            "{}",
            '{"binaries":{},"writer_exec_allow":"dotnet"}',
            '{"binaries":{"python":"python3"},"writer_exec_allow":[["python","-m","pytest"]]}',
        ):
            if bad is None:
                self.host.unlink()
            else:
                self.host.write_text(bad)
            code, run, _ = self.call(["python", "-m", "pytest"])
            assert code == 2
            run.assert_not_called()
        self.save()
        with mock.patch.object(Path, "read_text", side_effect=PermissionError):
            code, run, _ = self.call(["python", "-m", "pytest"])
        assert code == 2
        run.assert_not_called()
        assert len(self.rows()) == 7

    def test_even_configured_wrappers_and_unsafe_rules_are_refused(self):
        for rule in (["uv", "run"], ["sh", "-c"], ["just"], ["git", "grep", "-Osh"], ["python", "-c", "pass"]):
            self.doc["binaries"][rule[0]] = "/opt/pinned/" + rule[0]
            self.doc["writer_exec_allow"] = [rule]
            self.save()
            code, run, _ = self.call(rule)
            assert code == 2
            run.assert_not_called()

    def test_execution_error_returns_refusal_with_one_authorization_row(self):
        code, _, _ = self.call(["dotnet", "test"], spawn=mock.Mock(side_effect=OSError("missing")))
        assert code == 2
        assert len(self.rows()) == 1
        assert self.rows()[0]["allowed"]  # authorization is persisted before dispatch

    def test_audit_failure_refuses_before_execution(self):
        (self.root / "guard.jsonl").mkdir()
        code, run, why = self.call(["dotnet", "test"])
        assert code == 2
        run.assert_not_called()
        assert "audit" in why

    def test_audit_append_failure_refuses_before_execution(self):
        with mock.patch("delegate.app.codex_policy.JsonlLog.append_json", side_effect=OSError("full")):
            code, run, _ = self.call(["dotnet", "test"])
        assert code == 2
        run.assert_not_called()

    def test_authorization_is_persisted_before_dispatch(self):
        def spawn(file, argv, env):
            assert self.rows()[0]["resolved_argv"] == argv
            assert self.rows()[0]["allowed"]
            return 4242

        code, _, _ = self.call(["dotnet", "test"], spawn=spawn, exit_code=7)
        assert code == 7
        assert len(self.rows()) == 1
        assert [(r["exit"], r["head"], r["argv"]) for r in self.exits()] == [(7, "abc123", ["dotnet", "test"])]



class EscapeCorpus(Case):
    def test_every_reader_escape_is_refused(self):
        for command in ESCAPES:
            with self.subTest(command=command):
                assert read_only_problem(command) is not None


class HookFailures:
    def invoke(self, payload):
        with mock.patch("sys.stdin", io.StringIO(payload)), contextlib.redirect_stderr(io.StringIO()):
            return route.main(["guard"])

    def test_hook_fails_closed_and_audits_invalid_input_and_missing_config(self):
        for payload in (
            "",
            "{",
            "[]",
            "null",
            "{}",
            '{"tool_name":"Bash","tool_input":[]}',
            '{"tool_name":"Bash","tool_input":{"command":[]}}',
        ):
            assert self.invoke(payload) == 2
        (env.config_dir() / "host.json").unlink()
        assert self.invoke('{"tool_name":"Bash","tool_input":{"command":"cat f"}}') == 2
        rows = (env.config_dir() / "guard.jsonl").read_text().splitlines()
        assert len(rows) == 8
        assert all(not json.loads(row)["allowed"] for row in rows)

    def test_unexpected_error_is_audited_and_refused(self):
        with mock.patch("delegate.app.codex_policy.judge", side_effect=RuntimeError("broken")):
            code = self.invoke('{"tool_name":"Bash","tool_input":{"command":"cat f"}}')
        assert code == 2
        rows = (env.config_dir() / "guard.jsonl").read_text().splitlines()
        assert len(rows) == 1
        assert "RuntimeError" in json.loads(rows[0])["reason"]

    def test_hook_allows_and_refusals_each_have_one_row(self):
        for command, expected in (("cat f", 0), ("git push", 2), ("cat .env", 2)):
            assert self.invoke(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})) == expected
        rows = [json.loads(line) for line in (env.config_dir() / "guard.jsonl").read_text().splitlines()]
        assert [row["allowed"] for row in rows] == [True, False, False]


class WorktreeHead(Case):
    def test_head_is_read_from_the_git_files_of_a_plain_checkout_and_a_linked_worktree(self, tmp_path):
        root = tmp_path
        (root / "main" / ".git" / "refs" / "heads").mkdir(parents=True)
        (root / "main" / ".git" / "HEAD").write_text("ref: refs/heads/b\n")
        (root / "main" / ".git" / "refs" / "heads" / "b").write_text("c0ffee\n")
        link = root / "main" / ".git" / "worktrees" / "w"
        link.mkdir(parents=True)
        (link / "HEAD").write_text("ref: refs/heads/b\n")
        (link / "commondir").write_text("../..\n")
        (root / "w").mkdir()
        (root / "w" / ".git").write_text(f"gitdir: {link}\n")
        for where in ("main", "w"):
            with contextlib.chdir(root / where):
                assert worktree_head() == "c0ffee"
        with contextlib.chdir(root):
            assert worktree_head() == ""
