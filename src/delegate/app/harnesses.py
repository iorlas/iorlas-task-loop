"""Which harness serves which lane: the OpenCode profiles per lane, the login probe per lane, the transcript finder per family."""

from typing import Final

from any_agent.harnesses import claude, codex, opencode
from any_agent.harnesses.claude import ClaudeHarness
from any_agent.harnesses.codex import CodexHarness
from any_agent.harnesses.opencode import OpenCodeHarness, Profile
from any_agent.harnesses.opencode_sandbox import Sandbox
from any_agent.watch import Limits
from app_dirs import config_dir

from delegate.app import env

AUTH_TIMEOUT = 10
CLI_OF_KIND: Final = {"claude_p": "claude", "codex": "codex", "opencode": "opencode"}  # a runner kind (route.how) -> its CLI
# The deadlines a run is held to per CLI: each harness's own measured Limits. A test swaps one entry to shorten them.
LIMITS: Final[dict[str, Limits]] = {"claude": claude.LIMITS, "codex": codex.LIMITS, "opencode": opencode.LIMITS}
OC_PROFILES: Final = {
    "GROK_SUBSCRIPTION": Profile(auth_key="xai"),
    "ZAI_CODING_SUBSCRIPTION": Profile(providers=("zai-coding-plan",), price="unknown", auth_key="zai-coding-plan", need_key=True),
    "DEEPSEEK_FREE": Profile(providers=("opencode",), own_data=True, price="free"),
}
ZAI_MODELS = ("zai-coding-plan/glm-5.3", "zai-coding-plan/glm-5.3-flash")


def sandbox() -> Sandbox:
    """What delegate adds to the OpenCode sandbox: the task-loop runs folder (the engine points reviewers at its files) and the engine's
    git-ignored scratch folder (a reviewer's test run writes its temp files there)."""
    return Sandbox(readable=(str(config_dir("task-loop") / "runs"),), scratch=".task")


def probe_login(name: str):
    """-> (True | False | None, why): is the lane's login really there? A status command or a file, never a model call."""
    if name == "OPENAI_SUBSCRIPTION":
        return CodexHarness().login_probe(AUTH_TIMEOUT)
    if name == "CLAUDE_SUBSCRIPTION":
        return ClaudeHarness().login_probe(AUTH_TIMEOUT)
    if name in OC_PROFILES:
        return OpenCodeHarness(OC_PROFILES[name]).login_probe(AUTH_TIMEOUT)
    return None, "no check for this lane"


def find_transcript(ref: str | None, family: str):
    hx = {"openai": CodexHarness(), "claude": ClaudeHarness()}.get(family) or OpenCodeHarness(
        root=env.config_dir()
    )  # opencode: exported after the run
    return hx.transcript(ref)
