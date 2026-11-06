"""Text shaping that needs a regular expression. `import re` is allowed in domain/**/matchers.py only."""
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
