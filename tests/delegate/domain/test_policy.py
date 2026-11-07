"""domain/policy: the verdict on a worker's tool call, and the typed refusal record (D3)."""

from any_agent import events as ev

from delegate.app.codex_policy import hook_verdict
from delegate.app.launch import secret_in
from delegate.contracts.json_types import Json
from delegate.domain.policy.matchers import heredoc_only_hit
from delegate.domain.policy.shell import git_write, read_only_problem, writer_problem
from delegate.domain.policy.worker import READ_CAP_LINES, denial, denial_item, is_policy_denial, judge, read_verdict


class Policy:
    def test_a_secret_path_is_blocked_but_an_excluded_one_and_an_example_pass(self):
        assert judge("Bash", {"command": "cat ~/.ssh/id_rsa"}, False).blocked
        assert judge("Read", {"file_path": "/x/.env"}, False).blocked
        for ok in ("rg foo --glob '!**/.env*'", "cat .env.example", "grep -r x --exclude=.env ."):
            assert not judge("Bash", {"command": ok}, False).blocked, ok

    def test_a_secret_only_inside_a_heredoc_body_gets_the_apply_patch_hint(self):
        hd = "cat > a.py <<'EOF'\nopen('.env')\nEOF"
        assert heredoc_only_hit(hd)
        assert "apply_patch" in judge("Bash", {"command": hd}, False).reason
        assert not heredoc_only_hit("cat .env")

    def test_the_codex_watcher_ignores_a_secret_name_only_in_a_heredoc_body_but_not_a_read(self):
        hd = "zsh -lc \"python - <<'EOF'\nif path.name == '.env':\n    pass\nEOF\""
        assert secret_in(ev.Cmd(id="1", text=hd)) is None
        for read in ("cat .env", "cat .env <<'EOF'\nx\nEOF", "python -c \"open('.env')\""):
            assert secret_in(ev.Cmd(id="1", text=read)) == read

    def test_git_writes_are_blocked_and_listings_pass(self):
        for c in ("git commit -m x", "git -C . push", "bash -lc 'git checkout -b y'", "git stash", "git branch new"):
            assert git_write(c), c
            assert judge("Bash", {"command": c}, False).blocked, c
        for c in (
            "git -c core.pager=sh log",
            "git -ccore.hooksPath=x log",
            "git --config-env=a=B log",
            "git update-ref -d refs/heads/x",
            "git symbolic-ref HEAD refs/heads/x",
            "git branch -D x",
            "git tag -d v1",
            "git push origin :main",
            "git push --delete origin x",
            "git reflog expire --all",
            "git gc --prune=now",
        ):
            assert git_write(c), c
        for c in ("git status", "git -C sub log", "git stash list", "git branch --list", "git worktree list", "git log -1"):
            assert git_write(c) is None, c

    def test_git_config_and_environment_overrides_cannot_reopen_what_git_writes_close(self):
        for c in (
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git log",
            "GIT_CONFIG_PARAMETERS=\"'core.hooksPath=/x'\" git status",
            "export GIT_DIR=/elsewhere; git status",
            "GIT_EXEC_PATH=/x git log",
            "GIT_SSH_COMMAND=x git status",
            "git config core.hooksPath /x",
            "git config --global alias.x '!sh'",
            "git config --unset core.hooksPath",
            "git config --add remote.origin.pushurl x",
            "git remote add x y",
            "git remote set-url origin y",
            "git remote remove origin",
            "git filter-repo --path x",
            "git fast-import",
            "git fetch origin +refs/heads/x:refs/heads/main",
        ):
            assert git_write(c), c
            assert judge("Bash", {"command": c}, False).blocked, c
        for c in ("git config --get user.name", "git config user.email", "git config -l",
                  "git config --list --show-origin", "git remote -v",
                  "git remote show origin", "git remote get-url origin", "git remote", "git fetch origin", "git fetch origin main"):
            assert git_write(c) is None, c

    def test_a_write_step_may_not_use_the_forge_or_write_the_tracker(self):
        for c in (
            "gh pr merge 1",
            "bash -lc 'gh api x'",
            "bd create --title x",
            "bd close tl-1",
            "bd update tl-1 --claim",
            "bd",
            "dolt push",
            "dolt sql -q 'delete from t'",
            "FOO=1 gh issue list",
        ):
            assert writer_problem(c), c
            assert judge("Bash", {"command": c}, False).blocked, c
        for c in ("bd show tl-1", "bd list", "bd ready", "dolt status", "git log -1", "cat gh.txt"):
            assert writer_problem(c) is None, c

    def test_a_read_only_step_allows_only_reading(self):
        assert read_only_problem("git diff | head -5 && rg x") is None
        assert read_only_problem("rm x") == "`rm` is not a reading command"
        assert "redirection" in (read_only_problem("echo a > b") or "")
        assert judge("Bash", {"command": "touch x"}, True).blocked
        assert not judge("Bash", {"command": "touch x"}, False).blocked

    def test_the_denial_is_a_typed_record_with_the_matched_path(self):
        d = denial("secret", "Bash", {"command": "cat .env"})
        assert isinstance(d, ev.Denied)
        assert denial_item(d) == {"kind": "secret", "tool": "Bash", "path": ".env", "input": {"command": "cat .env"}, "reason": None}
        assert denial_item(denial("policy", "Bash", {}, "reviewer said no"))["reason"] == "reviewer said no"
        assert denial_item(denial("policy", "Read", {"file_path": "/a"}))["path"] == "/a"
        assert denial("x", "Bash", None).input == {}

    def test_a_git_write_or_a_read_only_violation_is_policy_not_the_owners_call(self):
        assert is_policy_denial("Bash", {"command": "git push"})
        assert is_policy_denial("Bash", {"command": "touch x"}, True)
        assert not is_policy_denial("Bash", {"command": "cat .env > x"}, True)  # a secret stays the owner's
        assert is_policy_denial("shell", {"command": "git push"})  # a shell by its command, not by its name
        assert not is_policy_denial("Read", {"file_path": "x"})


def test_a_whole_file_read_over_the_cap_is_blocked_with_a_pointer_to_range_reads():
    big: dict[str, Json] = {"file_path": "/x/big.py"}
    v = read_verdict("Read", big, READ_CAP_LINES + 1)
    assert v.blocked and "offset" in v.reason and "limit" in v.reason
    assert not read_verdict("Read", big, READ_CAP_LINES).blocked
    assert not read_verdict("Read", big | {"limit": 100}, 5000).blocked
    assert not read_verdict("Read", big | {"offset": 10}, 5000).blocked
    assert not read_verdict("Bash", {"command": "cat x"}, 5000).blocked
    assert not read_verdict("Read", big, None).blocked


def test_the_hook_blocks_a_whole_file_read_of_a_long_file_and_allows_a_range(tmp_path):
    f = tmp_path / "long.txt"
    f.write_text("x\n" * (READ_CAP_LINES + 5))
    assert hook_verdict({"tool_name": "Read", "tool_input": {"file_path": str(f)}}, False, ()).blocked
    assert not hook_verdict({"tool_name": "Read", "tool_input": {"file_path": str(f), "limit": 50}}, False, ()).blocked
    assert not hook_verdict({"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "missing")}}, False, ()).blocked
