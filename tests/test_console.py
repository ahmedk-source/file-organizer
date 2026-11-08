"""Tests for the terminal rendering helpers."""

from __future__ import annotations

from io import StringIO

import pytest

from file_organizer.console import Console


def make_console(*, color: bool = False, quiet: bool = False) -> tuple[Console, StringIO]:
    stream = StringIO()
    return Console(stream=stream, color=color, quiet=quiet), stream


def test_table_renders_headers_and_rows() -> None:
    console, stream = make_console()
    console.table(["Category", "Size"], [["Images", "1 KB"], ["PDF", "12 B"]], aligns=["l", "r"])

    lines = stream.getvalue().splitlines()
    assert lines[0] == "Category  Size"
    assert lines[1] == "--------  ----"
    assert "Images" in lines[2]
    assert lines[2].endswith("1 KB")


def test_table_rejects_mismatched_rows() -> None:
    console, _ = make_console()
    with pytest.raises(ValueError):
        console.table(["A", "B"], [["only one"]])
    with pytest.raises(ValueError):
        console.table([], [])


def test_style_is_a_noop_without_colour() -> None:
    console, _ = make_console(color=False)
    assert console.style("hello", "green") == "hello"


def test_style_adds_ansi_codes() -> None:
    console, _ = make_console(color=True)
    assert console.style("hello", "green", "bold") == "\033[32m\033[1mhello\033[0m"


def test_quiet_suppresses_info_but_not_write() -> None:
    console, stream = make_console(quiet=True)
    console.info("hidden")
    console.write("always")

    assert stream.getvalue() == "always\n"


def test_paragraph_wraps_with_an_indent() -> None:
    console, stream = make_console()
    console.paragraph("Label", "word " * 40, width=40)

    lines = stream.getvalue().splitlines()
    assert lines[0].startswith("Label       ")
    assert lines[1].startswith(" " * 12)


def test_colour_detection_respects_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTty(StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    assert Console._supports_color(FakeTty()) is True

    monkeypatch.setenv("NO_COLOR", "1")
    assert Console._supports_color(FakeTty()) is False

    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert Console._supports_color(FakeTty()) is False

    monkeypatch.delenv("TERM")
    assert Console._supports_color(StringIO()) is False
