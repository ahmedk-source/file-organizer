"""Minimal terminal rendering with optional ANSI colour.

The output is intentionally ASCII-only (no spinners, emoji or box drawing) so
it renders correctly in Windows terminals using legacy code pages.
"""

from __future__ import annotations

import os
import sys
import textwrap
from collections.abc import Sequence
from typing import TextIO

_ANSI_CODES = {
    "bold": "1",
    "dim": "2",
    "green": "32",
    "yellow": "33",
    "red": "31",
    "cyan": "36",
}


class Console:
    """A tiny wrapper around a text stream used by the CLI."""

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        color: bool | None = None,
        quiet: bool = False,
    ) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._quiet = quiet
        if color is None:
            color = self._supports_color(self._stream)
        self._color = color

    @staticmethod
    def _supports_color(stream: TextIO) -> bool:
        if os.environ.get("NO_COLOR") is not None:
            return False
        if os.environ.get("TERM") == "dumb":
            return False
        isatty = getattr(stream, "isatty", None)
        try:
            return bool(isatty()) if callable(isatty) else False
        except OSError:
            return False

    @property
    def quiet(self) -> bool:
        """Whether ``info`` output is suppressed."""
        return self._quiet

    def style(self, text: str, *styles: str) -> str:
        """Wrap *text* in ANSI styles when colour is enabled."""
        if not self._color or not styles:
            return text
        prefix = "".join(f"\033[{_ANSI_CODES[style]}m" for style in styles if style in _ANSI_CODES)
        return f"{prefix}{text}\033[0m" if prefix else text

    def write(self, text: str = "") -> None:
        print(text, file=self._stream)

    def info(self, text: str = "") -> None:
        """Print unless ``--quiet`` was requested."""
        if not self._quiet:
            self.write(text)

    def table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        *,
        aligns: Sequence[str] | None = None,
    ) -> None:
        """Print a simple aligned table."""
        if not headers:
            raise ValueError("a table needs at least one column")
        alignment = list(aligns) if aligns is not None else ["l"] * len(headers)
        widths = [len(header) for header in headers]
        for row in rows:
            if len(row) != len(headers):
                raise ValueError("every row must match the header width")
            widths = [max(width, len(cell)) for width, cell in zip(widths, row, strict=True)]

        def render(cells: Sequence[str]) -> str:
            parts = [
                cell.rjust(width) if align == "r" else cell.ljust(width)
                for cell, width, align in zip(cells, widths, alignment, strict=True)
            ]
            return "  ".join(parts).rstrip()

        self.write(render(headers))
        self.write("  ".join("-" * width for width in widths))
        for row in rows:
            self.write(render(row))

    def paragraph(self, label: str, text: str, *, width: int = 76) -> None:
        """Print a labelled, wrapped paragraph."""
        wrapper = textwrap.TextWrapper(
            width=width,
            initial_indent=f"{label:<12}",
            subsequent_indent=" " * 12,
            break_long_words=False,
            break_on_hyphens=False,
        )
        self.write(wrapper.fill(text))
