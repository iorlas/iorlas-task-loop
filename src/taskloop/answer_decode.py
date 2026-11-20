"""Shared answer constraints; each step owns its disposition and cross-field rules."""

from taskloop.answer_failures import AnswerFailure, AnswerRule
from taskloop.attempt_types import TRAILER, StepRules, path_allowed


def fields(value: object, keys: tuple[str, ...]) -> tuple[object, ...]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise AnswerFailure(AnswerRule.SHAPE, "Answer must be an object with exactly these keys: " + ", ".join(keys))
    return tuple(value[key] for key in keys)


def paths(value: object, rules: StepRules, *, unfinished: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(path, str) for path in value):
        raise AnswerFailure(AnswerRule.PATHS_SHAPE, "paths must be a list of strings")
    if unfinished:
        return ()
    if len(value) > rules.max_paths:
        raise AnswerFailure(AnswerRule.PATHS_COUNT, f"paths must contain at most {rules.max_paths} entries")
    found = tuple(path for path in value if isinstance(path, str))
    if len(set(found)) != len(found):
        raise AnswerFailure(AnswerRule.PATHS_DUPLICATE, "paths must contain unique entries")
    for index, path in enumerate(found):
        if not path_allowed(path, rules):
            root = rules.root or "the repository"
            raise AnswerFailure(
                AnswerRule.PATHS_LOCATION,
                f"paths[{index}] must be a relative allowed file under {root}, at most 255 bytes, with no excluded "
                "prefix, .git-prefixed component, empty/dot component, NUL, newline or backslash",
            )
    return found


def message(value: object, *, committing: bool) -> str | None:
    if not committing:
        if value is not None:
            raise AnswerFailure(AnswerRule.MESSAGE, "message must be null unless requesting a commit")
        return None
    if not (
        isinstance(value, str) and 1 <= len(value) <= 500 and "\0" not in value and TRAILER.casefold() + ":" not in value.casefold()
    ):
        raise AnswerFailure(
            AnswerRule.MESSAGE, "A commit message must be a string of 1 to 500 characters, without NUL or Task-Loop-Attempt:",
        )
    return value


def explanation(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2000:
        raise AnswerFailure(AnswerRule.EXPLANATION, "explanation must be a string of at most 2000 characters")
    return value
