"""domain/policy: the verdict on a worker's tool call, and the typed refusal record (D3)."""

from delegate.app.launch import secret_in
from delegate.contracts import events as ev
from delegate.domain.policy.matchers import heredoc_only_hit
from delegate.domain.policy.shell import git_write, read_only_problem, writer_problem
from delegate.domain.policy.worker import denial, denial_item, is_policy_denial, judge


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
        assert denial_item(d) == {"kind": "secret", "tool": "Bash", "path": ".env", "input": {"command": "cat .env"}}
        assert denial_item(denial("policy", "Read", {"file_path": "/a"}))["path"] == "/a"
        assert denial("x", "Bash", None).input == {}

    def test_a_git_write_or_a_read_only_violation_is_policy_not_the_owners_call(self):
        assert is_policy_denial("Bash", {"command": "git push"})
        assert is_policy_denial("Bash", {"command": "touch x"}, True)
        assert not is_policy_denial("Bash", {"command": "cat .env > x"}, True)  # a secret stays the owner's
        assert not is_policy_denial("Read", {"command": "git push"})
