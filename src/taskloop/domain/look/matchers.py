"""Text shaping for the look flow that needs a regular expression: a file-safe method name, an owner-look body's sections."""
import re


def safe_name(text: str) -> str:
    return re.sub(r"\W+", "_", text)


def sections(body: str) -> list[str]:
    """An owner-look bead's body split at its `## bead: title` headings."""
    return [x for x in re.split(r"\n\n(?=## )", body.strip()) if x]
