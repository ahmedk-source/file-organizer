"""Tests for planning, execution and undo."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from file_organizer import (
    Failure,
    Journal,
    JournalError,
    Organizer,
    Plan,
    Settings,
    Skip,
    undo_run,
)


def organise(
    make_settings: Callable[..., Settings],
    journal: Journal,
    source: Path,
    **overrides: Any,
) -> tuple[Organizer, Plan]:
    organizer = Organizer(make_settings(source, **overrides), journal=journal)
    return organizer, organizer.plan()


def test_plan_assigns_categories_without_touching_files(
    downloads: Path, write_file: Any, plan_factory: Any
) -> None:
    write_file(downloads / "photo.jpg")
    write_file(downloads / "invoice.pdf")
    write_file(downloads / "setup.exe")
    write_file(downloads / "mystery.xyz")

    _, plan = plan_factory(downloads)

    destinations = {move.source.name: move.destination.parent.name for move in plan.moves}
    assert destinations == {
        "photo.jpg": "Images",
        "invoice.pdf": "PDF",
        "setup.exe": "Programs",
        "mystery.xyz": "Other",
    }
    assert all(move.source.exists() for move in plan.moves)
    assert not (downloads / "Sorted").exists()


def test_plan_ignores_folders_and_empty_directories(
    downloads: Path, write_file: Any, plan_factory: Any
) -> None:
    (downloads / "empty").mkdir()
    write_file(downloads / "nested" / "file.txt")

    _, plan = plan_factory(downloads)

    assert plan.moves == ()
    assert plan.skipped == ()


def test_plan_reports_totals_per_category(
    downloads: Path, write_file: Any, plan_factory: Any
) -> None:
    write_file(downloads / "a.jpg", b"12345")
    write_file(downloads / "b.jpg", b"12345")
    write_file(downloads / "c.pdf", b"123")

    _, plan = plan_factory(downloads)

    summary = plan.by_category()
    assert summary["Images"].files == 2
    assert summary["Images"].total_bytes == 10
    assert summary["PDF"].files == 1
    assert plan.total_bytes == 13


def test_execute_moves_files_and_preserves_content(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "photo.jpg", b"image-bytes")
    write_file(downloads / "invoice.pdf", b"pdf-bytes")
    organizer, plan = organise(make_settings, journal, downloads)

    result = organizer.execute(plan)

    assert (downloads / "Sorted" / "Images" / "photo.jpg").read_bytes() == b"image-bytes"
    assert (downloads / "Sorted" / "PDF" / "invoice.pdf").read_bytes() == b"pdf-bytes"
    assert not (downloads / "photo.jpg").exists()
    assert len(result.completed) == 2
    assert result.failed == ()
    assert result.run_id
    assert len(journal.load(result.run_id)) == 2


def test_conflicting_file_is_renamed(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "Sorted" / "Images" / "photo.jpg", b"old")
    write_file(downloads / "photo.jpg", b"new")
    organizer, plan = organise(make_settings, journal, downloads)

    assert plan.moves[0].destination.name == "photo (1).jpg"
    organizer.execute(plan)
    assert (downloads / "Sorted" / "Images" / "photo.jpg").read_bytes() == b"old"
    assert (downloads / "Sorted" / "Images" / "photo (1).jpg").read_bytes() == b"new"


def test_identical_file_is_not_duplicated(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "Sorted" / "Images" / "photo.jpg", b"same")
    write_file(downloads / "photo.jpg", b"same")
    organizer, plan = organise(make_settings, journal, downloads)

    assert plan.moves == ()
    assert isinstance(plan.skipped[0], Skip)
    assert plan.skipped[0].reason == "identical file already exists"
    organizer.execute(plan)
    assert (downloads / "photo.jpg").exists()


def test_skip_policy_leaves_conflicts_alone(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "Sorted" / "Images" / "photo.jpg", b"old")
    write_file(downloads / "photo.jpg", b"new")
    organizer, plan = organise(make_settings, journal, downloads, on_conflict="skip")

    assert plan.moves == ()
    assert plan.skipped[0].reason == "destination already exists"
    organizer.execute(plan)
    assert (downloads / "photo.jpg").read_bytes() == b"new"


def test_overwrite_policy_replaces_the_existing_file(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "Sorted" / "Images" / "photo.jpg", b"old")
    write_file(downloads / "photo.jpg", b"new")
    organizer, plan = organise(make_settings, journal, downloads, on_conflict="overwrite")

    organizer.execute(plan)
    assert (downloads / "Sorted" / "Images" / "photo.jpg").read_bytes() == b"new"
    assert not (downloads / "photo.jpg").exists()


def test_same_name_inside_one_run_gets_a_unique_name(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "a" / "photo.jpg", b"a")
    write_file(downloads / "b" / "photo.jpg", b"b")
    organizer, plan = organise(make_settings, journal, downloads, recursive=True)

    names = sorted(move.destination.name for move in plan.moves)
    assert names == ["photo (1).jpg", "photo.jpg"]
    organizer.execute(plan)
    images = downloads / "Sorted" / "Images"
    assert {path.read_bytes() for path in images.iterdir()} == {b"a", b"b"}


def test_names_differing_only_in_case_are_kept_apart(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "a" / "photo.jpg", b"lower")
    write_file(downloads / "b" / "PHOTO.JPG", b"upper")
    _, plan = organise(make_settings, journal, downloads, recursive=True)

    keys = {move.destination.name.casefold() for move in plan.moves}
    assert len(keys) == 2


def test_folder_with_the_target_name_is_skipped(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    (downloads / "Sorted" / "Images" / "photo.jpg").mkdir(parents=True)
    write_file(downloads / "photo.jpg", b"data")
    organizer, plan = organise(make_settings, journal, downloads)

    assert plan.moves == ()
    assert plan.skipped[0].reason == "a folder already exists at the destination"
    organizer.execute(plan)
    assert (downloads / "photo.jpg").exists()


def test_incomplete_downloads_and_hidden_files_are_skipped(
    downloads: Path, write_file: Any, plan_factory: Any
) -> None:
    write_file(downloads / "video.mp4.crdownload")
    write_file(downloads / "archive.zip.part")
    write_file(downloads / ".hidden.txt")
    write_file(downloads / "notes.txt")

    _, plan = plan_factory(downloads)

    assert [move.source.name for move in plan.moves] == ["notes.txt"]
    reasons = {skip.source.name: skip.reason for skip in plan.skipped}
    assert reasons["video.mp4.crdownload"] == "incomplete download"
    assert reasons["archive.zip.part"] == "incomplete download"
    assert reasons[".hidden.txt"] == "hidden file"


def test_hidden_files_can_be_included(downloads: Path, write_file: Any, plan_factory: Any) -> None:
    write_file(downloads / ".hidden.txt")
    _, plan = plan_factory(downloads, skip_hidden=False)
    assert [move.source.name for move in plan.moves] == [".hidden.txt"]


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs extra privileges on Windows")
def test_symlinks_are_skipped_by_default(
    downloads: Path, write_file: Any, plan_factory: Any
) -> None:
    target = write_file(downloads / "real.txt")
    link = downloads / "link.txt"
    link.symlink_to(target)

    _, plan = plan_factory(downloads)
    reasons = {skip.source.name: skip.reason for skip in plan.skipped}
    assert reasons["link.txt"] == "symbolic link"

    _, followed = plan_factory(downloads, follow_symlinks=True)
    assert "link.txt" in {move.source.name for move in followed.moves}


def test_recursive_mode_collects_nested_files(
    downloads: Path, write_file: Any, plan_factory: Any
) -> None:
    write_file(downloads / "sub" / "deep" / "doc.pdf")
    write_file(downloads / "sub" / "photo.png")

    _, plan = plan_factory(downloads, recursive=True)

    assert {move.source.name for move in plan.moves} == {"doc.pdf", "photo.png"}


def test_destination_tree_is_never_scanned(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "photo.jpg")
    organizer, plan = organise(make_settings, journal, downloads)
    organizer.execute(plan)

    _, second_plan = organise(make_settings, journal, downloads, recursive=True)
    assert second_plan.moves == ()
    assert second_plan.skipped == ()


def test_the_state_directory_is_never_scanned(
    downloads: Path, write_file: Any, plan_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = downloads / ".state"
    write_file(state / "journal" / "run.jsonl", "{}")
    write_file(downloads / "photo.jpg")
    monkeypatch.setenv("FILE_ORGANIZER_STATE_DIR", str(state))

    _, plan = plan_factory(downloads, recursive=True)

    assert [move.source.name for move in plan.moves] == ["photo.jpg"]


def test_in_place_organisation_leaves_sorted_files_alone(
    downloads: Path, write_file: Any, plan_factory: Any
) -> None:
    write_file(downloads / "Images" / "photo.jpg")

    _, plan = plan_factory(downloads, destination=downloads, recursive=True)

    assert plan.moves == ()
    assert plan.skipped[0].reason == "already in the right place"


def test_move_failures_are_collected(
    downloads: Path,
    write_file: Any,
    make_settings: Any,
    journal: Journal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_file(downloads / "photo.jpg")
    blocked = write_file(downloads / "notes.txt")
    organizer, plan = organise(make_settings, journal, downloads)

    real_move = shutil.move

    def flaky_move(source: str, destination: str) -> str:
        if Path(source).name == "notes.txt":
            raise PermissionError("file is locked by another process")
        return real_move(source, destination)

    monkeypatch.setattr("file_organizer.organizer.shutil.move", flaky_move)

    result = organizer.execute(plan)

    assert len(result.completed) == 1
    assert len(result.failed) == 1
    assert isinstance(result.failed[0], Failure)
    assert result.failed[0].source == blocked
    assert "locked" in result.failed[0].reason
    assert blocked.exists()


def test_journal_failure_becomes_a_warning(
    downloads: Path,
    write_file: Any,
    make_settings: Any,
    journal: Journal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_file(downloads / "photo.jpg")
    organizer, plan = organise(make_settings, journal, downloads)

    def broken_record(self: Journal, record: Any) -> None:
        raise JournalError("disk full")

    monkeypatch.setattr(Journal, "record", broken_record)

    result = organizer.execute(plan)

    assert len(result.completed) == 1
    assert result.warnings and "disk full" in result.warnings[0]


def test_undo_restores_files_and_prunes_empty_folders(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "photo.jpg", b"image")
    write_file(downloads / "notes.txt", b"text")
    organizer, plan = organise(make_settings, journal, downloads)
    result = organizer.execute(plan)

    undone = undo_run(journal, result.run_id)

    assert {move.source.name for move in undone.restored} == {"photo.jpg", "notes.txt"}
    assert (downloads / "photo.jpg").read_bytes() == b"image"
    assert (downloads / "notes.txt").read_bytes() == b"text"
    assert not (downloads / "Sorted" / "Images").exists()
    assert journal.is_undone(result.run_id)


def test_undo_dry_run_changes_nothing(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "photo.jpg")
    organizer, plan = organise(make_settings, journal, downloads)
    result = organizer.execute(plan)

    undone = undo_run(journal, result.run_id, dry_run=True)

    assert undone.dry_run is True
    assert len(undone.restored) == 1
    assert not (downloads / "photo.jpg").exists()
    assert journal.is_undone(result.run_id) is False


def test_undo_skips_files_that_disappeared(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "photo.jpg")
    organizer, plan = organise(make_settings, journal, downloads)
    result = organizer.execute(plan)
    (downloads / "Sorted" / "Images" / "photo.jpg").unlink()

    undone = undo_run(journal, result.run_id)

    assert undone.restored == ()
    assert undone.skipped[0].reason == "file no longer exists"
    assert journal.is_undone(result.run_id) is True


def test_undo_skips_occupied_original_locations(
    downloads: Path, write_file: Any, make_settings: Any, journal: Journal
) -> None:
    write_file(downloads / "photo.jpg", b"original")
    organizer, plan = organise(make_settings, journal, downloads)
    result = organizer.execute(plan)
    write_file(downloads / "photo.jpg", b"replacement")

    undone = undo_run(journal, result.run_id)

    assert undone.restored == ()
    assert "original location is occupied" in undone.skipped[0].reason
    assert (downloads / "Sorted" / "Images" / "photo.jpg").exists()
    assert (downloads / "photo.jpg").read_bytes() == b"replacement"
    assert journal.is_undone(result.run_id) is False


def test_undo_of_an_unknown_run_is_reported(journal: Journal) -> None:
    with pytest.raises(JournalError):
        undo_run(journal, "does-not-exist")


def test_undo_of_an_empty_run_does_not_mark_it_undone(journal: Journal) -> None:
    run_id = journal.begin(Path("/a"), Path("/a/Sorted"), run_id="empty-run")

    undone = undo_run(journal, run_id)

    assert undone.restored == ()
    assert journal.is_undone(run_id) is False
