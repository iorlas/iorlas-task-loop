"""Match supplied paths with the engine's glob dialect."""
from tlkernel.checkmatchers import expand_braces, glob_re


def cmd_match(args: list[str]) -> int:
    """Print paths matching any glob before the required `--` separator."""
    if "--" not in args:
        raise SystemExit("usage: tl match GLOB... -- PATH...")
    split = args.index("--")
    patterns = [glob_re(alt) for glob in args[:split] for alt in expand_braces(glob)]
    matched = [path for path in args[split + 1:] if any(pattern.match(path) for pattern in patterns)]
    for path in matched:
        print(path)
    return int(not matched)
