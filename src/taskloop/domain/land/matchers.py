"""Policy over the text of a push: the only regular expressions of the land feature, each one a named class."""
import re

_TRANSIENT = re.compile(
    r"curl \d+|Broken pipe|Connection (?:reset|timed out|refused)|Could not resolve host|early EOF|RPC failed|"
    r"remote end hung up|SSL_ERROR|TLS|Operation timed out|Network is unreachable|"
    r"Temporary failure in name resolution|error: 5\d\d|HTTP/\d(?:\.\d)? 5\d\d",
    re.I,
)
_REJECTED = re.compile(r"rejected|non-fast-forward|fetch first|stale info")
_FAILED_PREFIX = re.compile(r"^(failed|paused): ")


class Push:
    """A push's last lines: what died of the network (curl 56 broken pipe after a long hook) and what main's moving rejected."""

    @staticmethod
    def transient(tail: str) -> bool:
        return _TRANSIENT.search(tail[-600:]) is not None  # the push's own last lines, not a hook's test output before them

    @staticmethod
    def rejected(tail: str) -> bool:
        return _REJECTED.search(tail) is not None


def without_prefix(why: str) -> str:
    """A stop's reason without its "failed: " or "paused: " lead."""
    return _FAILED_PREFIX.sub("", why)
