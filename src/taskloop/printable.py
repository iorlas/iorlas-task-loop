"""The one way a person's or an agent's text reaches a terminal or a tracker comment: printable, one line, capped."""

import unicodedata


def one_line(text: str, cap: int = 300) -> str:
    """`text` as one printable line of at most `cap` characters: every control, format, surrogate, private-use or
    unassigned character becomes a space, then every run of whitespace (line and paragraph separators included) one."""
    kept = "".join(" " if unicodedata.category(char).startswith("C") else char for char in text)
    return " ".join(kept.split())[:cap].rstrip()


def block(text: str, line: int = 2000, total: int = 20000) -> str:
    """`text` for a terminal: each line through `one_line` (at most `line` characters, its leading spaces kept up to 20), at
    most `total` characters in all."""
    body = "\n".join(each[:len(each) - len(each.lstrip(" "))][:20] + one_line(each, line) for each in text.split("\n"))
    return body if len(body) <= total else body[:total].rstrip() + "\n[shortened]"


def title_line(text: str, cap: int, tail: str = "") -> str:
    """`text` as one printable line that, with `tail`, fits `cap` characters: a longer one is cut at a word boundary and
    ends in an ellipsis (a single word longer than the room is cut, then the ellipsis)."""
    line, room = one_line(text, 10**6), max(cap - len(tail), 2)
    if len(line) <= room:
        return line + tail
    cut = line[:room - 1]
    if line[room - 1] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "\u2026" + tail
