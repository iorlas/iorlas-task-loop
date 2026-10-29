"""gitignore rules as regexes: the part of git's pathspec and exclude language the engine's repos use."""
import re

Rule = tuple[bool, bool, "re.Pattern[str]"]  # negated, only for directories, the path it matches (from the repo root)


def glob_re(pat: str) -> str:
    out, i = "", 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pat.startswith("/**", i) and i + 3 == len(pat):
            out, i = out + "/.*", i + 3
        elif pat.startswith("**", i):
            out, i = out + ".*", i + 2
        elif c == "*":
            out, i = out + "[^/]*", i + 1
        elif c == "?":
            out, i = out + "[^/]", i + 1
        elif c == "[" and (j := pat.find("]", i + 2)) > 0:
            out, i = out + pat[i:j + 1], j + 1
        else:
            out, i = out + re.escape(c), i + 1
    return out


def rules_of(base: str, text: str) -> list[Rule]:
    """The rules of one .gitignore (or exclude file) that sits in folder `base` ('' for the root)."""
    rules: list[Rule] = []
    for raw in text.splitlines():
        ln = raw.rstrip()
        if not ln or ln.startswith("#"):
            continue
        neg = ln.startswith("!")
        pat = ln[1:] if neg else ln
        only_dir = pat.endswith("/")
        pat = pat.rstrip("/")
        anchored = "/" in pat
        body = glob_re(pat.lstrip("/"))
        head = re.escape(base + "/") if base else ""
        rules.append((neg, only_dir, re.compile(f"^{head}{'' if anchored else '(?:.*/)?'}{body}$")))
    return rules


def ignored(path: str, rules: list[Rule]) -> bool:
    """Whether `path` (a file) is ignored: it, or a folder above it, matches; the last matching rule of a level wins."""
    parts = path.split("/")
    for n in range(1, len(parts) + 1):
        p, is_dir = "/".join(parts[:n]), n < len(parts)
        verdict = False
        for neg, only_dir, rx in rules:
            if (is_dir or not only_dir) and rx.match(p):
                verdict = not neg
        if verdict:
            return True
    return False
