"""Word matching for asks: the one place a pattern is applied to an ask's text, and only to compare two questions."""
import re
from typing import Final

WORD: Final = re.compile(r"[a-z][a-z0-9_.-]{2,}")


def words(text: str) -> list[str]:
    """The lower-case words of a question: three characters or more, starting with a letter."""
    return WORD.findall(text.lower())
