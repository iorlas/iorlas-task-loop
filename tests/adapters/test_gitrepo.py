"""Checkout discovery ignores stray .git directories (tl-wika)."""

from taskloop.adapters.gitrepo import pinned_env


def test_pinned_env_ignores_empty_git_directory(workdir):
    (workdir / ".git").mkdir()
    checkout = workdir / "checkout"
    gitdir = checkout / ".git"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/main\n")
    inner = checkout / "subdir"
    inner.mkdir()
    outside = workdir / "outside"
    outside.mkdir()

    assert pinned_env(inner) == {"GIT_DIR": str(gitdir.resolve()), "GIT_WORK_TREE": str(checkout.resolve())}
    assert pinned_env(outside) == {}
