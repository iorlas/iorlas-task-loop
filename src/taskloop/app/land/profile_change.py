"""Owner-only profile delivery: explicit words, process context and the exact patch hash."""
import hashlib

from taskloop.contracts.env import Env
from taskloop.contracts.envvars import registered
from taskloop.contracts.ports import Git


def owner_refusal(text: str | None, env: Env) -> str:
    if text is None:
        return ""
    settings = ("TASK_LOOP_DASH_", "TASK_LOOP_SUITE_")
    if any(registered(name) and not name.startswith(settings) for name in env.vars):
        return "profile change is an owner decision; not available to the engine or a lane"
    if len(text.strip()) < 12 or not any(char.isdigit() for char in text):
        return "land-stack: --profile-change requires the owner's words and a timestamp (at least 12 characters and a digit)"
    return ""


def diff_sha(git: Git, repo: str, base: str, tip: str) -> str:
    return hashlib.sha256(git.profile_diff(repo, base, tip).encode("utf-8")).hexdigest()
