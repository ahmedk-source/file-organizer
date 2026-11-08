"""Shared fixtures for the test-suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from file_organizer import Journal, Organizer, Plan, Settings, resolve_settings


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every test hermetic: no real Downloads folder, no real journal.

    ``Path.home()`` is redirected to an empty folder so a developer's
    personal ``~/.file-organizer.toml`` can never influence test results.
    """
    state = tmp_path / "state"
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    def _fake_home(cls: type[Path]) -> Path:
        return fake_home

    monkeypatch.setenv("FILE_ORGANIZER_STATE_DIR", str(state))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(_fake_home))
    monkeypatch.chdir(tmp_path)
    return state


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    return folder


@pytest.fixture
def write_file() -> Any:
    def _write(path: Path, content: bytes | str = b"payload") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        path.write_bytes(data)
        return path

    return _write


@pytest.fixture
def make_settings() -> Any:
    def _make(source: Path, **overrides: Any) -> Settings:
        return resolve_settings(source, **overrides)

    return _make


@pytest.fixture
def plan_factory(make_settings: Any) -> Any:
    def _plan(source: Path, **overrides: Any) -> tuple[Organizer, Plan]:
        organizer = Organizer(make_settings(source, **overrides))
        return organizer, organizer.plan()

    return _plan


@pytest.fixture
def journal(tmp_path: Path) -> Journal:
    return Journal(root=tmp_path / "journal")
