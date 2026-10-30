"""Text shaping for the look flow that needs a regular expression: picture names in prose, a file-safe method name,
an owner-look body's sections."""
import re
from typing import Final

IMAGE_NAME: Final = re.compile(r"[\w./-]+\.(?:png|jpe?g)\b", re.I)


def image_names(text: str) -> list[str]:
    """The image file names a text mentions, each once, in order."""
    return list(dict.fromkeys(IMAGE_NAME.findall(text)))


def safe_name(text: str) -> str:
    return re.sub(r"\W+", "_", text)


def sections(body: str) -> list[str]:
    """An owner-look bead's body split at its `## bead: title` headings."""
    return [x for x in re.split(r"\n\n(?=## )", body.strip()) if x]


def writer_names(path: str, said: str) -> bool:
    """The writer's answers name this file: its full path or its basename, on word boundaries (not `ab.md` for `b.md`)."""
    return any(re.search(rf"(?<![\w.-]){re.escape(n)}(?![\w-]|\.\w)", said) for n in dict.fromkeys((path, path.rsplit("/", 1)[-1])))
