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


def spec_match(path: str, spec: list[str]) -> bool:
    """Whether `path` is under the git pathspecs `spec`: `:(literal)` and plain words name a file or a folder, `:(glob)` a pattern,
    `:(exclude,...)` takes paths out."""
    def one(item: str) -> tuple[bool, bool]:
        magic, rest = (item[2:].split(")", 1)[0].split(","), item.split(")", 1)[1]) if item.startswith(":(") else ([], item)
        if "glob" in magic:
            hit = bool(re.fullmatch(glob_re(rest), path))
        elif "literal" in magic or not any(ch in rest for ch in "*?["):
            hit = rest in (".", "") or path == rest or path.startswith(rest.rstrip("/") + "/")
        else:
            hit = bool(re.fullmatch(glob_re(rest).replace("[^/]*", ".*"), path))
        return hit, "exclude" in magic
    marks = [one(s) for s in spec]
    inc = [h for h, ex in marks if not ex]
    return (any(inc) or not inc) and not any(h for h, ex in marks if ex)
