"""Narrowing for tests: a value a test knows is present, said once, so the type checker and the reader both agree."""


def must[T](value: T | None) -> T:
    assert value is not None, "expected a value, got None"
    return value
