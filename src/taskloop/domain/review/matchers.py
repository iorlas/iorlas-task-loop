"""Policy over the prose of review and verify items: the only regular expressions of the review feature, each one a named class with a
table test (tests/review/test_matchers.py). An item is what a worker wrote ("the engine files the beads", "ruff passes"); a matcher says
what the item is about, nothing more."""
import re
from collections.abc import Iterable

KNOWN_TOOLS = frozenset({
    "ruff", "black", "flake8", "pylint", "mypy", "pyright", "isort", "bandit", "eslint", "prettier", "tsc", "biome", "stylelint",
    "shellcheck", "shfmt", "hadolint", "yamllint", "markdownlint", "actionlint", "golangci-lint", "gofmt", "staticcheck", "clippy",
    "rustfmt", "rubocop", "ktlint", "detekt", "swiftlint", "clang-tidy", "clang-format", "cppcheck", "csharpier", "semgrep",
    "codespell", "vale", "pre-commit", "prek"})
_RUN_VERB = r"(?:run|runs|ran|running|lint|lints|linted|linting|format|formats|formatted|check|checks|checked)"
_BACKTICKED = re.compile(r"`([^`]+)`")
_PLAIN_WORD = re.compile(r"[a-z][a-z0-9+-]*")
_TOOL_AFTER_VERB = re.compile(rf"\b{_RUN_VERB}\s+(?:(?:with|by|using|the)\s+)?([a-z][a-z0-9+-]*)")
_SAFE_CMD = re.compile(r"[\w./=:,@+*~ -]+")
_CODE_EXT = re.compile(r"\.(?:py|cs|js|jsx|ts|tsx|go|rs|java|kt|rb|sh|c|h|cpp|hpp|json|ya?ml|toml|md|txt|csv|sql|css|html|gd|"
                       r"lua|swift|asmdef|unity|prefab)$", re.I)
_SYMBOL = re.compile(r"\b(?:[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+|[a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")
_URL = re.compile(r"https?://\S+")
_PATH_LIKE = re.compile(r"[\w][\w./-]*[\w]")


def word_in(name: str, text: str) -> bool:
    """`name` stands in `text` as a whole name: not inside a longer word, nor a longer dash-joined name."""
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) is not None


class Tools:
    """Linters and formatters an item names."""

    @staticmethod
    def named(what: str) -> list[str]:
        """The tools an unchecked item names: the first word of a backticked command with arguments (`ruff check tools`), or a known
        linter or formatter backticked (`mypy`) or right after a run, lint, format or check verb ("ran ruff"). Prose that only contains
        a tool's name ("the biome transition") names none."""
        found = []
        for cmd in _BACKTICKED.findall(what):
            words = cmd.split()
            if (len(words) > 1 and _PLAIN_WORD.fullmatch(words[0])) or cmd.strip().lower() in KNOWN_TOOLS:
                found.append(words[0].lower())
        found += [w for w in _TOOL_AFTER_VERB.findall(what.lower()) if w in KNOWN_TOOLS]
        return list(dict.fromkeys(found))

    @staticmethod
    def plain_command(what: str, tool: str) -> str:
        """The backticked command of `tool` in the item when it is plain words (no shell syntax), else ''."""
        for c in _BACKTICKED.findall(what):
            if c.split()[:1] == [tool] and _SAFE_CMD.fullmatch(c):
                return c.strip()
        return ""


class CodeNames:
    """What in an item a check could reach: a repo path, a code or config file name, a code symbol."""

    @staticmethod
    def tokens(what: str) -> list[str]:
        return _PATH_LIKE.findall(_URL.sub(" ", what))

    @staticmethod
    def is_code_file(token: str) -> bool:
        return _CODE_EXT.search(token) is not None

    @staticmethod
    def symbols(what: str) -> set[str]:
        """The CamelCase and snake_case names in the item."""
        return set(_SYMBOL.findall(_URL.sub(" ", what).replace(".", " ")))


class EngineActions:
    """What the engine itself does after the stages (so an item that asks for it is the engine's, not the writer's)."""

    FILES = re.compile(r"\b(?:fil(?:e|es|ed|ing)|creat(?:e|es|ed|ing)|open(?:s|ed|ing)?)\b.*\b(?:follow-?ups?|leftovers?)\b|"
                       r"\b(?:follow-?ups?|leftovers?)\b.*\b(?:not filed|filed|files?|creat\w+)\b", re.I)
    BEADS = re.compile(r"\bfil(?:e|es|ed|ing)\s+(?:(?:the|a|an|these|those|all|each|new|nine|\d+|follow-?ups?)\s+)*beads?\b|"
                       r"\bcreat(?:e|es|ed|ing)\s+(?:(?:the|a|an|these|those|all|each|new|nine|\d+|follow-?ups?)\s+)*beads?\b|"
                       r"\bbeads?\b[^.]{0,40}\b(?:to be (?:filed|created)|(?:is |are )?(?:not )?filed|to file)\b", re.I)
    LANDS = re.compile(r"\b(?:at|after|before|on) (?:the )?land(?:ing)?\b|\bthe engine (?:lands|merges|pushes|runs the gate)\b|"
                       r"\bthe (?:land )?gate (?:runs|will run)\b", re.I)
    CLOSES = re.compile(r"\bclos(?:e|es|ed|ing)\b[^.]*\bbead\b|\bbead\b[^.]*\bclos(?:e|es|ed|ing)\b", re.I)

    @classmethod
    def files_beads(cls, what: str) -> bool:
        """The item is about filing follow-ups or beads."""
        return cls.FILES.search(what) is not None or cls.BEADS.search(what) is not None

    @classmethod
    def lands_or_closes(cls, what: str) -> bool:
        return cls.LANDS.search(what) is not None or cls.CLOSES.search(what) is not None


class BdDemand:
    """A demand only the engine can meet: bd (the writer and the reviewer cannot run it), another operating system (the host is macOS
    and runs the gate), a follow-up bead to file. A review that asks for one is routed to the ledger, never sent back (tl-7y6.7.6)."""

    BD = re.compile(r"\bbd\s+(?:comment|create|close|update|show|note|issue)|\bwriters?\b[^.]{0,30}\bbarred from\b[^.]{0,10}\bbd\b|"
                    r"\b(?:fil\w*|clos\w*|fold\w*|creat\w*|open\w*)\b[^.;]{0,30}\b(?:follow-?ups?|beads?|tickets?)\b|"
                    r"\b(?:follow-?ups?|beads?)\b[^.;]{0,40}"
                    r"\b(?:unfiled|not filed|to (?:be )?(?:file[d]?|creat\w+)|the engine files)|"
                    r"\bbeads?\b(?:[^.;]|\.\w){0,60}\bnot (?:yet )?(?:closed|folded)\b|"
                    r"\bnot (?:yet )?written (?:in)?to (?:the )?bead\b", re.I)
    OTHER_OS = re.compile(r"\b(?:on|under|for)\s+(?:windows|linux|ubuntu|wsl|cmd\.exe|powershell)\b|\bwindows[- ]only\b", re.I)
    GOAL_MET = re.compile(r"^\s*(?:the\s+)?(?:stage\s+)?(?:goal|task|work)\s+(?:is|has been|was)\s+(?:fully\s+)?(?:met|done|achieved|"
                          r"complete[d]?)\b|\bnothing\s+(?:is\s+)?(?:missing|unmet)\b|"
                          r"\ball\s+(?:requirements|criteria)\s+(?:are\s+)?met\b", re.I)

    @classmethod
    def is_bd(cls, text: str) -> bool:
        return cls.BD.search(text) is not None

    @classmethod
    def is_other_os(cls, text: str) -> bool:
        return cls.OTHER_OS.search(text) is not None

    @classmethod
    def is_goal_met(cls, text: str) -> bool:
        """A remark that something is fine, written where a gap belongs ("the stage goal is met")."""
        return cls.GOAL_MET.search(text) is not None

    @classmethod
    def engine_only(cls, text: str) -> str:
        """'bd', 'os' or 'met' when the item asks for something only the engine can do (or is no gap at all), else ''."""
        if cls.is_goal_met(text):
            return "met"
        if cls.is_bd(text):
            return "bd"
        return "os" if cls.is_other_os(text) else ""


class Wording:
    """Words that say what an item is about: filing and recording (the ledger's own subject), the owner's call, a look."""

    FILING = re.compile(r"\b(?:beads?|follow-?ups?|filed?|filing|issues?|tickets?|records?|recorded|leftovers?|deferred?)\b", re.I)
    OWNERISH = re.compile(r"\b(?:owner|sign-?off|approv\w*|review|confirm\w*|decid\w*|decision)\b", re.I)
    LOOK = re.compile(r"owner\b[^.]{0,40}\b(?:judge|check|decide|assess|review|verify)\b[^.]*\b"
                      r"(?:looks?|visual\w*|appearance|screenshots?)\b", re.I)  # 'Only the owner can judge the look.'
    UNVERIFIED = re.compile(r"\bunverified\b", re.I)

    @classmethod
    def about_filing(cls, what: str) -> bool:
        return cls.FILING.search(what) is not None

    @classmethod
    def ownerish(cls, text: str) -> bool:
        return cls.OWNERISH.search(text) is not None

    @classmethod
    def is_look(cls, what: str) -> bool:
        return cls.LOOK.search(what) is not None

    @classmethod
    def marked_unverified(cls, line: str) -> bool:
        return cls.UNVERIFIED.search(line) is not None


class GateProof:
    """An item settles from the engine's own results only in a narrow form (tl-bxk.10.19, .25): its sole doubt is that the verifier cannot
    prove the engine ran or passed a check, and it names that check. An item about coverage, skips, fakes or a check that never ran is
    a claim about the check, not its result."""

    HEDGE_LIGHT = re.compile(r"\b(?:flaky|stale|though|but|yet|however|although|unless|except|new tests?)\b")
    PROVES = re.compile(r"\b(passe[sd]?|passing|is green|stays? green|green|runs?|ran|exits? 0)\b|engine-run")
    NOT_PROOF = re.compile(r"\b(covers?|covered|coverage|a tests? for|skipped|false green|never (?:been )?run|not run|only tested|"
                           r"fake|untested|not tested)\b")
    OTHER_DOUBT = re.compile(r"\b(behaviou?rs?|looks?|visual(?:ly)?|screens?|screenshots?|layout|render\w*|devices?|manual(?:ly)?|"
                             r"by hand|ui|ux|taste|feels?|edge cases?|regress\w*|race|crash\w*|coverage|covers?|covered|fake|"
                             r"false green|bug)\b")
    CANNOT_PROVE = re.compile(r"\b(?:cannot|can not|unable to) (?:prove|verify|confirm|see)\b|\bno (?:saved )?logs?\b")
    HEDGE = re.compile(r"\b(?:not|never|no|nor|none|nothing|without|flaky|stale|only|yet|though|but|unless|except|missing|"
                       r"still|also|however|although|wrong|fails?|failed|new tests?)\b|n't")
    CHECK_LIKE = re.compile(r"`([^`]+)`|(?<![\w.-])([\w.]*[-_./*][\w.*/-]*)")

    @classmethod
    def says_it_passes(cls, what: str) -> bool:
        """Lower-cased item text that says a named check passes or runs, without hedging or a claim about the check."""
        return not (cls.NOT_PROOF.search(what) or cls.HEDGE_LIGHT.search(what)) and cls.PROVES.search(what) is not None

    @classmethod
    def first_named(cls, what: str, names: Iterable[str]) -> str:
        """The first of `names` that stands in the item as a whole name, else ''."""
        return next((n for n in names if word_in(n, what)), "")

    @classmethod
    def only_doubts_the_run(cls, what: str) -> bool:
        """Lower-cased: the item says the verifier cannot prove a check ran, and doubts nothing else."""
        if not cls.CANNOT_PROVE.search(what) or cls.OTHER_DOUBT.search(what):
            return False
        return not cls.HEDGE.search(cls.CANNOT_PROVE.sub(" ", what))

    @classmethod
    def check_names(cls, what: str) -> list[str]:
        """Every check-like name in the lower-cased item (a backticked word, or a word with a dash, dot, slash or star)."""
        return [(m.group(1) or m.group(2)).strip(".,;:").lower() for m in cls.CHECK_LIKE.finditer(what)]


class AcceptanceItems:
    """The items of a bead's acceptance text: one per bullet or numbered line (a text with no list is one item)."""

    BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*\S)\s*$")

    @classmethod
    def split(cls, text: str) -> list[tuple[str, str]]:
        """[(A1, text), ...]; a bullet's continuation lines belong to it."""
        items: list[str] = []
        for line in text.splitlines():
            m = cls.BULLET.match(line)
            if m:
                items.append(m.group(1))
            elif line.strip() and items:
                items[-1] += " " + line.strip()
            elif line.strip():
                items.append(line.strip())
        return [(f"A{n}", " ".join(t.split())) for n, t in enumerate(items, 1)]
