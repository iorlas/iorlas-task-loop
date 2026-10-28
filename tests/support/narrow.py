"""Narrowing for tests: a value a test knows is present, said once, so the type checker and the reader both agree."""


def must[T](value: T | None) -> T:
    assert value is not None, "expected a value, got None"
    return value


def only[T](cls: type[T], value: object) -> T:
    """The value, known to be an instance of `cls` (the test says which of a union's members it expects)."""
    assert isinstance(value, cls), "expected %s, got %r" % (cls.__name__, value)
    return value
