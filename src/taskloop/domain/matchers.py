"""Text shaping that needs a regular expression. `import re` is allowed in domain/**/matchers.py only."""
import re

OPEN_CODE = re.compile(r"\s*-?\s*`[^`]*?(?: \.\.\.)?$")


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
