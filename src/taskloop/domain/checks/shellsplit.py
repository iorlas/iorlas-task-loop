"""A shell command cut at its top level, without a shell."""


def quoted_at(text: str, idx: int) -> bool:
    """True when position idx of `text` sits inside a '...' or "..." span."""
    q, i = "", 0
    while i < idx:
        ch = text[i]
        if q:
            if ch == "\\" and q == '"':
                i += 1
            elif ch == q:
                q = ""
        elif ch == "\\":
            i += 1
        elif ch in "'\"":
            q = ch
        i += 1
    return bool(q)


def split_top(cmd: str) -> list[tuple[str, str]] | None:
    """[(segment, separator)] cut at top-level `&&`, `;` and newlines; None when the command has a top-level `||`, a
    background `&`, or quoting/nesting this scan does not follow (then it is not split)."""
    segs: list[tuple[str, str]] = []
    cur, i, depth, quote = "", 0, 0, ""
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            cur += ch
            if ch == "\\" and quote == '"' and i + 1 < len(cmd):
                cur += cmd[i + 1]
                i += 1
            elif ch == quote:
                quote = ""
        elif ch == "\\" and i + 1 < len(cmd):
            cur += cmd[i:i + 2]
            i += 1
        elif ch in "'\"`":
            quote = ch
            cur += ch
        elif ch in "({)}":
            depth += 1 if ch in "({" else -1
            cur += ch
        elif depth == 0 and cmd.startswith("&&", i):
            segs.append((cur, "&&"))
            cur, i = "", i + 1
        elif depth == 0 and (cmd.startswith("||", i) or (ch == "&" and not cmd.startswith(">&", i - 1) and not cmd.startswith("&>", i))):
            return None
        elif depth == 0 and ch in ";\n":
            segs.append((cur, ch))
            cur = ""
        else:
            cur += ch
        i += 1
    if quote or depth:
        return None
    segs.append((cur, ""))
    return segs
