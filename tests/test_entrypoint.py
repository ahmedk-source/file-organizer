"""Smoke tests for the module entry point and package metadata."""

from __future__ import annotations

import runpy
import sys
from importlib.metadata import version

import pytest

from file_organizer import __version__


def test_version_matches_installed_metadata() -> None:
    assert version("file-organizer") == __version__


def test_module_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["file-organizer", "--version"])

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("file_organizer", run_name="__main__", alter_sys=True)

    assert exit_info.value.code == 0
    assert f"file-organizer {__version__}" in capsys.readouterr().out
