"""The runners route.py can launch, as data: the runner kind `route.how()` names, the CLI it drives (the key of
app/harnesses.LIMITS), the executable to look for, and whether resume was tested. What a CLI does (argv, events, usage) lives in its
harness class (the shelf's any_agent).
(the shelf's any_agent).

Account facts that are data, not code, live here too (`ACCOUNT_HOSTS`: the API hosts an account needs, for adapters/netprobe).
"""

from collections import namedtuple
from types import MappingProxyType

Adapter = namedtuple("Adapter", "kind cli exe resume")
# resume: "tested" = spike P1 (62-spikes-resume.md) resumed a killed session on this CLI; "untested" = opencode, blocked by ENOTFOUND
# opencode.ai last time
REGISTRY = MappingProxyType(
    {
        "codex": Adapter("codex", "codex", "codex", "tested"),
        "opencode": Adapter("opencode", "opencode", "opencode", "untested"),
        "claude_p": Adapter("claude_p", "claude", "claude", "tested"),
    }
)

ACCOUNT_HOSTS = MappingProxyType(
    {
        "CLAUDE_SUBSCRIPTION": ("api.anthropic.com",),
        "OPENAI_SUBSCRIPTION": ("chatgpt.com",),
        "GROK_SUBSCRIPTION": ("api.x.ai",),
        "DEEPSEEK_FREE": ("opencode.ai",),
        "ZAI_CODING_SUBSCRIPTION": ("api.z.ai",),
    }
)
FAMILY_HOSTS = MappingProxyType(
    {
        "claude": ("api.anthropic.com",),
        "openai": ("chatgpt.com",),
        "xai": ("api.x.ai",),
        "deepseek": ("opencode.ai",),
        "zai": ("api.z.ai",),
    }
)


def hosts_of(account: str | None):
    return ACCOUNT_HOSTS.get(account or "", ())


def hosts_for_family(family: str | None):
    return FAMILY_HOSTS.get(family or "", ())


def all_hosts():
    return tuple(dict.fromkeys(h for hs in ACCOUNT_HOSTS.values() for h in hs))


LOGIN_CMD = MappingProxyType(
    {
        "OPENAI_SUBSCRIPTION": "codex login",
        "CLAUDE_SUBSCRIPTION": "claude auth login",
        "GROK_SUBSCRIPTION": "opencode auth login",
        "ZAI_CODING_SUBSCRIPTION": "opencode auth login, choose Z.AI Coding Plan",
        "DEEPSEEK_FREE": "route.py config set profile.accounts.DEEPSEEK_FREE enabled",
    }
)
