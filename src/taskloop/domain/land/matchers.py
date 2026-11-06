"""Policy over the text of a push: the only regular expressions of the land feature, each one a named class."""
import re
from typing import Final

_TRANSIENT: Final = re.compile(
    r"curl \d+|Broken pipe|Connection (?:reset|timed out|refused)|Could not resolve host|early EOF|RPC failed|"
    r"remote end hung up|SSL_ERROR|TLS|Operation timed out|\(timed out after|Network is unreachable|"
    r"Temporary failure in name resolution|error: 5\d\d|HTTP/\d(?:\.\d)? 5\d\d",
    re.I,
)
_NETWORK: Final = re.compile(
    r"could not resolve host|temporary failure in name resolution|"
    r"unable to access[^\n]*(?:could not resolve|connection timed out|connection refused|failed to connect|"
    r"network is unreachable|ssl connection timeout|operation timed out)|"
    r"connection reset by peer|early eof|the remote end hung up unexpectedly|kex_exchange_identification|"
    r"ssh: connect to host[^\n]*(?:timed out|refused|unreachable|resolve)",
    re.I,
)
_REJECTED: Final = re.compile(r"\[rejected\].*(?:non-fast-forward|fetch first|stale info)")
_LFS_ATTR: Final = re.compile(r"^[^#\n]*\bfilter=lfs\b", re.M)
_NO_REMOTE: Final = re.compile(r"no (?:dolt )?remotes?\b|remote[^\n]{0,40}not (?:configured|found)|no such remote|no upstream", re.I)
_FAILED_PREFIX: Final = re.compile(r"^(failed|paused): ")


class NetText:
    """Git transport evidence; an authentication or repository access error alone is no network outage."""

    @staticmethod
    def down(tail: str) -> bool:
        return _NETWORK.search(tail[-600:]) is not None


class Push:
    """A push's last lines: what died of the network (curl 56 broken pipe after a long hook) and what main's moving rejected."""

    @staticmethod
    def transient(tail: str) -> bool:
        return _TRANSIENT.search(tail[-600:]) is not None  # the push's own last lines, not a hook's test output before them

    @staticmethod
    def rejected(tail: str) -> bool:
        # Mirror RefRejected: every refused ref must be a moved-base/lease rejection.
        # Hook text and [remote rejected] rows are policy refusals, even when they mention a race.
        refused = [line for line in tail.splitlines() if line.lstrip().startswith("!")]
        return bool(refused) and all(_REJECTED.search(line) is not None for line in refused)


def lfs_in(attributes: str) -> bool:
    """A .gitattributes with a line that puts files in Git LFS."""
    return _LFS_ATTR.search(attributes) is not None


def no_dolt_remote(text: str) -> bool:
    """bd's words when the repo has no Dolt remote to push to."""
    return _NO_REMOTE.search(text) is not None


def without_prefix(why: str) -> str:
    """A stop's reason without its "failed: " or "paused: " lead."""
    return _FAILED_PREFIX.sub("", why)
