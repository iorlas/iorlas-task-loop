"""The layers of a test and their limits. A test's layer comes from its path (tests/<slice>/real/ is real, tests/e2e/ is e2e), never from a
hand marker; a test over its layer's limit fails. Pure functions and numbers: the pytest hooks that apply them stay with the tree."""

# Seconds of work a test's call may do, by kind. TL_TIME_SCALE multiplies them. Logic tests are judged by the work they do (the
# instructions retired, else CPU time), real and e2e by CPU time including waited-for children; the wall clock only catches a hang.
LIMITS_S = {"logic": 2.0, "real": 15.0, "e2e": 30.0, "live": 3600.0}
RULES_LIMIT_S = 15.0  # the gate's rules read the whole tree
WALL_FACTOR = 10
HANG_S = 300.0
UNGUARDED = ("e2e", "live")  # first folder names that are their own kind; live runs the real pieces with no guard


def kind_of_parts(parts: tuple[str, ...], *, marked_real: bool = False) -> str:
    """logic / real / e2e / live, from a test file's path parts below the tests folder (the file name last). `marked_real`: the single
    test carries its own real_proc / needs mark or a real_git attribute."""
    if parts[0] in UNGUARDED:
        return parts[0]
    if "real" in parts[:-1] or marked_real:
        return "real"
    return "logic"


def limit_for(kind: str, *, rules: bool = False, module_limit: float = 0.0) -> float:
    """The seconds a test of this kind may work: the kind's limit, the rules' floor under tests/rules, a module's own larger one."""
    limit = LIMITS_S[kind]
    if rules:
        limit = max(limit, RULES_LIMIT_S)
    return max(limit, module_limit)


def hang_s(limit: float, scale: float = 1.0) -> float:
    """The wall seconds after which a test counts as hung, whatever it worked."""
    return max(HANG_S * scale, limit * WALL_FACTOR)
