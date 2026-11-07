"""Text shaping that needs a regular expression. Shared regular expressions live in tlkernel.matchers."""
import re
from typing import Final

OPEN_CODE: Final = re.compile(r"\s*-?\s*`[^`]*?(?: \.\.\.)?$")
_NETWORK: Final = re.compile(
    r"could not resolve host|temporary failure in name resolution|"
    r"unable to access[^\n]*(?:could not resolve|connection timed out|connection refused|failed to connect|"
    r"network is unreachable|ssl connection timeout|operation timed out)|"
    r"connection reset by peer|early eof|the remote end hung up unexpectedly|kex_exchange_identification|"
    r"ssh: connect to host[^\n]*(?:timed out|refused|unreachable|resolve)",
    re.I,
)


def clip(text: str | None, n: int = 170) -> str:
    """text cut to at most n characters at a sentence end, else a clause end, else a word: never mid-word. A cut code span
    (an unclosed backtick, or a dash-list dump after a colon) goes."""
    t = " ".join((text or "").split())
    if len(t) > n:
        head = t[:n]
        for seps in ((". ", "! ", "? "), ("; ", ": "), (", ", " ")):
            at = max(head.rfind(x) for x in seps)
            if at >= n // 3:
                t = head[:at].rstrip(" ,;:(") + ("" if seps[0] == ". " else " ...")
                break
        else:
            t = head.rstrip(" ,;:(") + " ..."
    t = OPEN_CODE.sub("", t).rstrip(" ,;:(") if t.count("`") % 2 else t
    return t if not t or t[-1] in ".!?)'\"`" or len(t) < n * 0.9 else t + " ..."  # near the cap and no end: cut at its source


class NetText:
    """Git transport evidence; an authentication or repository access error alone is no network outage."""

    @staticmethod
    def down(tail: str) -> bool:
        return _NETWORK.search(tail[-600:]) is not None


_SECRETS: Final = (
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("assigned secret", re.compile(r"""(?i)\b\w*(?:secret|token|passw(?:or)?d|api_?key)\w*\s*[:=]\s*["'][A-Za-z0-9/+_.-]{20,}["']""")),
)


def secrets_added(diff: str) -> list[str]:
    """The kinds of credential on the lines a patch adds (a `+` line, not the `+++` header), once each, in order of first sight."""
    found: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for kind, rx in _SECRETS:
            if kind not in found and rx.search(line):
                found.append(kind)
    return found


_BLOCK: Final = re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----.*?(?:-----END (?:[A-Z]+ )*PRIVATE KEY-----|\Z)", re.S)


def redact(text: str) -> str:
    """`text` with every credential of the kinds `secrets_added` names replaced by `[redacted <kind>]`: a private key block whole, a key or
    token or assigned value where it stands. What the engine writes to a bead (Dolt keeps it) passes through here (tl-7i9k.53, M-070)."""
    text = _BLOCK.sub("[redacted private key]", text)
    for kind, rx in _SECRETS[1:]:
        text = rx.sub(f"[redacted {kind}]", text)
    return text
