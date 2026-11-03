"""macOS available memory from vm_stat; Linux uses the existing cgroup-aware reader."""


def available_mb(text: str) -> int | None:
    """Free, inactive and speculative pages can serve a new worker; active and wired pages cannot."""
    lines = text.splitlines()
    if not lines:
        return None
    try:
        page_size = int(lines[0].split("page size of ", 1)[1].split()[0])
        pages = {}
        for line in lines[1:]:
            name, sep, value = line.partition(":")
            if sep and name in ("Pages free", "Pages inactive", "Pages speculative"):
                pages[name] = int(value.strip().rstrip("."))
        return sum(pages.values()) * page_size // (1 << 20) if "Pages free" in pages else None
    except (ValueError, IndexError):
        return None
