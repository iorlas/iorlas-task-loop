"""The text matchers of the worker policy: the one place of the domain that reads shell text with a regex (D3). Pure functions of a
command line."""

import re

from any_shell_policy import parse, strip_excluded

# Paths a worker must never touch: credentials outside the repo and .env files in it (.env.example and kin are fine). A tripwire for
# accidents and lazy injections, not a boundary: a determined worker can spell a path so it does not match.
SECRET_RE = re.compile(
    r"\.ssh\b|\.gnupg\b|\.aws\b|\.azure\b|\.config/gh\b|\.docker/config\.json|\.netrc\b|\.git-credentials\b|"
    r"\.config/task-loop\b|(?<![\w.-])auth\.json\b|Library/Keychains|(?<![\w.-])\.env(?:\.(?!(?:example|sample|template|dist)\b)[\w-]+)?(?![\w.-])"
)
# Arguments that keep a path OUT of a search or listing (rg --glob '!**/.env*', grep --exclude, find -not -path, git ':!x'): a worker
# avoiding a secret must not trip the guard.
EXCLUDED_RE = re.compile(
    r"""(?:--i?glob|-g)[=\s]+(?:(['"])!.*?\1|!\S+)|--exclude(?:-dir)?[=\s]+(?:(['"]).*?\2|\S+)"""
    r"""|(?:-not|!)\s+-i?(?:path|name|wholename|regex)\s+(?:(['"]).*?\3|\S+)|(['"]):(?:!|\(exclude\))[^'"]*\4|(?<!\S):(?:!|\(exclude\))\S+"""
)
SED_PRINT_RE = re.compile(r"\s*(?:(?:\d+|\$)(?:,(?:\d+|\$))?)?[pP]\s*(?:;\s*(?:(?:\d+|\$)(?:,(?:\d+|\$))?)?[pP]\s*)*")


def sed_print_only(args: list[str]) -> bool:
    """Only inline print scripts; external scripts and sed's exec/write commands never qualify as readers."""
    scripts: list[str] = []
    i = 0
    while i < len(args):
        word = args[i]
        if word in ("-e", "--expression"):
            i += 1
            if i == len(args):
                return False
            scripts.append(args[i])
        elif word.startswith("--expression="):
            scripts.append(word.partition("=")[2])
        elif word.startswith("-e"):
            scripts.append(word[2:])
        elif word in ("-n", "--quiet", "--silent", "-E", "-r"):
            pass
        elif word.startswith("-"):
            return False
        elif not scripts:
            scripts.append(word)
        i += 1
    return bool(scripts) and all(SED_PRINT_RE.fullmatch(script) for script in scripts)


def command_text(text: str, bodies: bool = True) -> str | None:
    """`text` as shell words (quote splicing collapsed, here-document bodies kept) with the arguments that keep a path OUT of a search
    removed; None if unparsable."""
    commands = parse(text)
    if commands is None:
        return None
    return " ".join(w for c in commands for w in (*c.assigns, *strip_excluded(c.argv), *c.redirects, c.stdin or "" if bodies else "") if w)


def secret_hit(text: str | None, bodies: bool = True) -> str | None:
    """The secret path `text` names, ignoring paths it only excludes (and, without `bodies`, here-document bodies); None when none."""
    text = text or ""
    stripped = command_text(text, bodies)
    m = SECRET_RE.search(stripped if stripped is not None else EXCLUDED_RE.sub(" ", text))
    return m.group() if m else None


def heredoc_only_hit(cmd: str | None) -> bool:
    """True when `cmd` names a secret path only inside a heredoc body (code being written), not in the command itself."""
    cmd = cmd or ""
    return bool(secret_hit(cmd) and not secret_hit(cmd, bodies=False))


def pieces(cmd: str, bare: bool = False) -> list[list[str]] | None:
    """The command lines in `cmd` as words, after separators, `sh -c` and loops are looked through and `NAME=v` assignments and wrappers
    (sudo, env, ...) are stripped; with `bare` they stay, so a reader that starts with a wrapper is not a reader. None when unparsable."""
    commands = parse(cmd)
    if commands is None:
        return None
    return [[*c.assigns, *c.argv] if bare else list(c.words) for c in commands if c.words or (bare and (c.assigns or c.argv))]

# A git setting passed in the environment does what `git -c` does (core.hooksPath turns the push gate off; a pager, ssh command or exec path
# names a program), and GIT_DIR / GIT_WORK_TREE point git at another repository.
GIT_ENV = re.compile(
    r"(?<![\w])GIT_(?:CONFIG_\w+|EXEC_PATH|SSH(?:_COMMAND)?|ASKPASS|EXTERNAL_DIFF|PAGER|EDITOR|SEQUENCE_EDITOR|PROXY_COMMAND|DIR|WORK_TREE)=")
