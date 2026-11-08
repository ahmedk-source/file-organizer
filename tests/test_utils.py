"""Tests for the small utility helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from file_organizer.utils import (
    describe_error,
    human_size,
    is_hidden,
    is_partial_download,
    same_content,
    sha256_of,
    state_directory,
    utc_now_iso,
)


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (5 * 1024 * 1024, "5.0 MB"),
        (1024**5, "1.0 PB"),
    ],
)
def test_human_size(size: int, expected: str) -> None:
    assert human_size(size) == expected


def test_human_size_rejects_negative_values() -> None:
    with pytest.raises(ValueError):
        human_size(-1)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("report.pdf", False),
        ("report.pdf.part", True),
        ("movie.mp4.crdownload", True),
        ("archive.zip.CRDOWNLOAD", True),
        ("notes.txt", False),
    ],
)
def test_is_partial_download(name: str, expected: bool) -> None:
    assert is_partial_download(Path(name)) is expected


def test_hidden_dotfiles_are_detected() -> None:
    assert is_hidden(Path(".gitignore")) is True
    assert is_hidden(Path("regular.txt")) is False


def test_same_content_compares_bytes(tmp_path: Path, write_file: Any) -> None:
    first = write_file(tmp_path / "a.txt", b"same bytes")
    second = write_file(tmp_path / "b.txt", b"same bytes")
    different = write_file(tmp_path / "c.txt", b"other")

    assert same_content(first, second) is True
    assert same_content(first, different) is False
    assert same_content(first, tmp_path / "missing.txt") is False
    assert sha256_of(first) == sha256_of(second)


def test_state_directory_can_be_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "custom-state"
    monkeypatch.setenv("FILE_ORGANIZER_STATE_DIR", str(target))
    assert state_directory() == target


def test_utc_timestamp_is_iso_8601() -> None:
    value = utc_now_iso()
    assert "T" in value
    assert value.endswith("+00:00")


def test_describe_error_prefers_the_message() -> None:
    assert describe_error(PermissionError("locked")) == "locked"
    assert describe_error(ValueError()) == "ValueError"
