"""Live-file reads retain complete-line byte cursors across polls and rotation."""

from delegate import api

LINE = b'{"t":1,"kind":"text","text":"hello"}\n'


def test_partial_line_waits_and_cursor_continues(tmp_path):
    path = tmp_path / "01-write.jsonl"
    path.write_bytes(LINE + LINE[:-1])
    first = api.live_read(str(tmp_path), "01-write")
    assert [line.offset for line in first.lines] == [0]
    assert first.cursor == len(LINE)
    assert not first.reset and first.ident != 0
    waiting = api.live_read(str(tmp_path), "01-write", first.cursor, first.ident)
    assert waiting.lines == [] and waiting.cursor == first.cursor
    path.write_bytes(LINE + LINE)
    after = api.live_read(str(tmp_path), "01-write", waiting.cursor, waiting.ident)
    assert [line.offset for line in after.lines] == [len(LINE)]
    assert after.cursor == 2 * len(LINE) and not after.reset


def test_bad_lines_are_skipped_but_advance_cursor(tmp_path):
    bad = b'nope\n[]\n{"t":1}\n{"t":"bad","kind":"text"}\n{"t":1,"kind":""}\n'
    (tmp_path / "a.jsonl").write_bytes(bad + LINE)
    result = api.live_read(str(tmp_path), "a")
    assert [line.offset for line in result.lines] == [len(bad)]
    assert result.lines[0].event == {"t": 1, "kind": "text", "text": "hello"}
    assert result.cursor == len(bad + LINE)


def test_shrink_resets_from_zero(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_bytes(LINE * 2)
    first = api.live_read(str(tmp_path), "a")
    path.write_bytes(LINE)
    result = api.live_read(str(tmp_path), "a", first.cursor, first.ident)
    assert result.reset and result.cursor == len(LINE)
    assert [line.offset for line in result.lines] == [0]


def test_replaced_inode_resets_from_zero(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_bytes(LINE)
    first = api.live_read(str(tmp_path), "a")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(LINE * 2)
    replacement.replace(path)
    result = api.live_read(str(tmp_path), "a", first.cursor, first.ident)
    assert result.reset and result.ident != first.ident
    assert [line.offset for line in result.lines] == [0, len(LINE)]


def test_missing_file_clears_cursor_and_identity(tmp_path):
    assert api.live_read(str(tmp_path), "missing") == api.LiveRead(lines=[], cursor=0, ident=0, reset=False)
    assert api.live_read(str(tmp_path), "missing", 12, 34) == api.LiveRead(lines=[], cursor=0, ident=0, reset=True)


def test_files_are_sorted_by_name(tmp_path):
    for name in ("02-write.jsonl", "01-plan.jsonl", "other.txt"):
        (tmp_path / name).write_bytes(LINE)
    found = api.live_files(str(tmp_path))
    assert [file.name for file in found] == ["01-plan", "02-write"]
    assert [file.mtime for file in found] == [(tmp_path / f"{file.name}.jsonl").stat().st_mtime for file in found]
    assert api.live_files(str(tmp_path / "missing")) == []


def test_reads_are_bounded_and_continue_through_a_backlog(tmp_path):
    count = (1 << 20) // len(LINE) + 2
    (tmp_path / "a.jsonl").write_bytes(LINE * count)
    first = api.live_read(str(tmp_path), "a")
    assert 0 < first.cursor <= 1 << 20
    assert len(first.lines) == first.cursor // len(LINE)
    after = api.live_read(str(tmp_path), "a", first.cursor, first.ident)
    assert first.cursor + len(after.lines) * len(LINE) == count * len(LINE)
    assert after.cursor == count * len(LINE)
