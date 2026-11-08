"""An ADR as the file `docs/adr/NNNN-title.md` of the repo. The file is the record: an account writes it and lands it like any change (the
`tl adr` outcome files a bead whose body is `template`; tl itself never writes into a checkout). `parse` reads one file into the
`Adr` the plan stage and the dashboard use; the number is the file name's, the rest is the `- Key: value` lines and the sections."""
from collections.abc import Mapping

from tlkernel.ledger import Adr

DIR = "docs/adr"
LABEL = "adr"  # the bead that will land (or retire) an ADR carries it: a proposed ADR is "pending" while that bead is open
SECTIONS = ("Question", "Answer", "Decision")


def slug(text: str) -> str:
    kept = "".join(c if c.isascii() and c.isalnum() else " " for c in text.lower())
    return "-".join(kept.split())[:48].strip("-") or "decision"


def file_name(n: int, title: str) -> str:
    return f"{n:04d}-{slug(title)}.md"


def title_of(text: str) -> str:
    first = (text.strip().splitlines() or [""])[0].strip()
    return first[:80]


def render(adr: Adr) -> str:
    """The file's text for `adr` (its number and the retirement included)."""
    head = [("Status", "retired" if adr.retired_t is not None else "accepted"), ("Ask", adr.ask), ("Bead", adr.bead), ("Key", adr.key),
            ("Date", repr(adr.t)), ("By", adr.by)]
    if adr.retired_t is not None:
        head += [("Retired-by", adr.retired_by), ("Retired-at", repr(adr.retired_t))]
    lines = [f"# ADR-{adr.n}: {title_of(adr.text)}", "", *(f"- {k}: {v}" for k, v in head), ""]
    for name, body in zip(SECTIONS, (adr.question, adr.answer, adr.text), strict=True):
        lines += [f"## {name}", "", body.strip(), ""]
    return "\n".join(lines)


def template(ask: str, bead: str, key: str, question: str, answer: str, text: str, by: str, now: float) -> str:
    """The body of the bead that lands an ADR: what to write (next number, the file's shape) and the decision itself."""
    sample = render(Adr(id="ADR-N", n=0, repo="", text=text, question=question, answer=answer, ask=ask, bead=bead, key=key, t=now,
                        by=by))
    return (f"Land this decision as `{DIR}/NNNN-<title>.md` (NNNN: the next free number in the folder; the title is a short slug). "
            "Replace `ADR-N` and the heading number by it. Keep the `- Key: value` lines and the three sections as they are: "
            f"tl reads them.\n\n```markdown\n{sample}```")


def parse(name: str, text: str, repo: str = "") -> Adr | None:
    """The ADR a file holds; None for a file that is not one (no number in its name)."""
    base = name.rsplit("/", 1)[-1]
    digits, _, rest = base.partition("-")
    if len(digits) < 4 or not digits.isascii() or not digits.isdigit() or not rest.endswith(".md"):
        return None
    n = int(digits)
    fields: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current:
            sections[current].append(line)
        elif line.startswith("- ") and ":" in line:
            key, _, value = line[2:].partition(":")
            fields[key.strip().lower()] = value.strip()
    body = {k: "\n".join(v).strip() for k, v in sections.items()}

    def number(key: str) -> float | None:
        try:
            return float(fields[key])
        except (KeyError, ValueError):
            return None

    retired = fields.get("status") == "retired"
    return Adr(id=f"ADR-{n}", n=n, repo=repo, text=body.get("Decision", ""), question=body.get("Question", ""),
               answer=body.get("Answer", ""), ask=fields.get("ask", ""), bead=fields.get("bead", ""), key=fields.get("key", ""),
               t=number("date") or 0.0, by=fields.get("by", ""), retired_by=fields.get("retired-by", "") if retired else "",
               retired_t=(number("retired-at") or 0.0) if retired else None)


def parse_all(files: Mapping[str, str], repo: str = "") -> list[Adr]:
    found = (parse(name, text, repo) for name, text in files.items())
    return sorted((a for a in found if a is not None), key=lambda a: a.n)
