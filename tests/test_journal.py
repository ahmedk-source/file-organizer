"""Tests for the append-only journal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_organizer import Journal, JournalError, MoveRecord
from file_organizer.utils import utc_now_iso


def record(run_id: str, index: int = 1) -> MoveRecord:
    return MoveRecord(
        run_id=run_id,
        timestamp=utc_now_iso(),
        source=f"/downloads/file{index}.txt",
        destination=f"/downloads/Sorted/Documents/file{index}.txt",
        category="Documents",
    )


def test_records_round_trip(journal: Journal) -> None:
    run_id = journal.begin(Path("/downloads"), Path("/downloads/Sorted"), run_id="run-1")
    journal.record(record(run_id, 1))
    journal.record(record(run_id, 2))

    loaded = journal.load(run_id)
    assert [item.source for item in loaded] == [
        "/downloads/file1.txt",
        "/downloads/file2.txt",
    ]
    assert loaded[0].category == "Documents"
    assert journal.exists(run_id)


def test_unknown_run_is_reported(journal: Journal) -> None:
    with pytest.raises(JournalError, match="unknown run"):
        journal.load("missing")
    with pytest.raises(JournalError, match="unknown run"):
        journal.info("missing")


@pytest.mark.parametrize("run_id", ["../escape", "with space", "", ".hidden", "a/b"])
def test_invalid_run_ids_are_rejected(journal: Journal, run_id: str) -> None:
    with pytest.raises(JournalError, match="invalid run id"):
        journal.load(run_id)


def test_recording_before_beginning_is_rejected(tmp_path: Path) -> None:
    journal = Journal(root=tmp_path / "journal")
    with pytest.raises(JournalError, match="was not started"):
        journal.record(record("run-404"))


def test_latest_run_skips_undone_runs(journal: Journal) -> None:
    first = journal.begin(Path("/a"), Path("/a/Sorted"), run_id="run-a")
    journal.record(record(first))
    second = journal.begin(Path("/b"), Path("/b/Sorted"), run_id="run-b")

    assert journal.latest_run_id() == second
    journal.mark_undone(second)
    assert journal.is_undone(second) is True
    assert journal.latest_run_id() == first
    assert journal.latest_run_id(only_undoable=False) == second

    journal.mark_undone(first)
    assert journal.latest_run_id() is None


def test_runs_are_listed_newest_first_with_counts(journal: Journal) -> None:
    first = journal.begin(Path("/a"), Path("/a/Sorted"), run_id="run-a")
    journal.record(record(first, 1))
    journal.record(record(first, 2))
    second = journal.begin(Path("/b"), Path("/b/Sorted"), run_id="run-b")

    runs = journal.runs()
    assert [run.run_id for run in runs] == [second, first]
    assert runs[1].move_count == 2
    assert runs[1].undone is False


def test_truncated_lines_are_ignored(journal: Journal) -> None:
    run_id = journal.begin(Path("/a"), Path("/a/Sorted"), run_id="run-1")
    journal.record(record(run_id))
    path = journal.root / f"{run_id}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type": "move", "source": "/trunc')

    assert len(journal.load(run_id)) == 1


def test_corrupt_header_is_reported(journal: Journal) -> None:
    journal.root.mkdir(parents=True, exist_ok=True)
    (journal.root / "broken.jsonl").write_text("not json\n", encoding="utf-8")

    assert journal.runs() == []
    with pytest.raises(JournalError, match="corrupt"):
        journal.info("broken")


def test_unknown_moves_are_skipped(journal: Journal) -> None:
    run_id = journal.begin(Path("/a"), Path("/a/Sorted"), run_id="run-1")
    path = journal.root / f"{run_id}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "move", "source": "/x"}) + "\n")
        handle.write(json.dumps({"type": "other", "source": "/y", "destination": "/z"}) + "\n")

    assert journal.load(run_id) == []
