"""`must(x)`: x, which a test knows is not None (the assertion fails the test, and tells the type checker so)."""


def must[T](x: T | None) -> T:
    assert x is not None
    return x
