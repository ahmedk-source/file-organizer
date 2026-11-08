"""Tests for configuration loading and validation."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from file_organizer import ConfigError, ConflictPolicy, load_rules, resolve_settings


def write_config(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_defaults_are_safe_and_predictable(downloads: Path) -> None:
    settings = resolve_settings(downloads)
    assert settings.source == downloads.resolve()
    assert settings.destination == (downloads / "Sorted").resolve()
    assert settings.recursive is False
    assert settings.skip_hidden is True
    assert settings.follow_symlinks is False
    assert settings.on_conflict is ConflictPolicy.RENAME
    assert settings.config_path is None


def test_cli_values_win_over_the_config_file(downloads: Path) -> None:
    config = write_config(
        downloads / "file-organizer.toml",
        """
        [general]
        recursive = true
        on_conflict = "skip"
        skip_hidden = false
        """,
    )
    settings = resolve_settings(
        downloads,
        recursive=False,
        on_conflict="overwrite",
        skip_hidden=True,
        config_path=config,
    )
    assert settings.recursive is False
    assert settings.on_conflict is ConflictPolicy.OVERWRITE
    assert settings.skip_hidden is True


def test_config_is_discovered_in_the_current_directory(downloads: Path) -> None:
    config = write_config(
        Path.cwd() / "file-organizer.toml",
        """
        [general]
        destination = "Organized"
        """,
    )
    settings = resolve_settings(downloads)
    assert settings.config_path == config
    assert settings.destination == (downloads / "Organized").resolve()


def test_relative_source_is_resolved_against_the_config_file(tmp_path: Path) -> None:
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    config = write_config(
        tmp_path / "conf" / "file-organizer.toml",
        """
        [general]
        source = "../Downloads"
        """,
    )
    settings = resolve_settings(config_path=config)
    assert settings.source == downloads.resolve()


def test_destination_is_resolved_against_the_source(downloads: Path) -> None:
    config = write_config(
        downloads / "file-organizer.toml",
        """
        [general]
        destination = "ByType"
        """,
    )
    settings = resolve_settings(downloads, config_path=config)
    assert settings.destination == (downloads / "ByType").resolve()


def test_relative_cli_source_is_resolved_against_the_working_directory(
    downloads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(downloads.parent)

    settings = resolve_settings("Downloads")

    assert settings.source == downloads.resolve()


def test_environment_variables_are_expanded(
    downloads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = downloads.parent / "elsewhere"
    monkeypatch.setenv("FILE_ORGANIZER_TEST_DEST", str(target))
    config = write_config(
        downloads / "file-organizer.toml",
        """
        [general]
        destination = "$FILE_ORGANIZER_TEST_DEST"
        """,
    )
    settings = resolve_settings(downloads, config_path=config)
    assert settings.destination == target.resolve()


def test_categories_from_the_config_file_are_applied(downloads: Path) -> None:
    config = write_config(
        downloads / "file-organizer.toml",
        """
        [categories]
        Design = [".fig", "sketch"]
        """,
    )
    settings = resolve_settings(downloads, config_path=config)
    assert settings.rules.category_for_filename("mockup.fig") == "Design"
    assert settings.rules.category_for_filename("mockup.sketch") == "Design"


def test_default_category_can_be_changed(downloads: Path) -> None:
    config = write_config(
        downloads / "file-organizer.toml",
        """
        [general]
        default_category = "Misc"
        """,
    )
    settings = resolve_settings(downloads, config_path=config)
    assert settings.rules.category_for_filename("unknown.xyz") == "Misc"
    assert settings.rules.default_category == "Misc"


def test_in_place_destination_is_allowed(downloads: Path) -> None:
    settings = resolve_settings(downloads, destination=downloads)
    assert settings.destination == settings.source


@pytest.mark.parametrize(
    "body",
    [
        """
        [unknown]
        value = 1
        """,
        """
        [general]
        recursiv = true
        """,
        """
        [general]
        recursive = "yes"
        """,
        """
        [general]
        skip_hidden = 1
        """,
        """
        [general]
        default_category = 5
        """,
        """
        [general]
        on_conflict = "explode"
        """,
        """
        [general]
        destination = ""
        """,
        """
        [categories]
        Images = ".png"
        """,
        """
        [categories]
        Bad/Name = [".png"]
        """,
    ],
)
def test_invalid_configuration_is_rejected(downloads: Path, body: str) -> None:
    config = write_config(downloads / "file-organizer.toml", body)
    with pytest.raises(ConfigError):
        resolve_settings(downloads, config_path=config)


def test_missing_config_file_is_reported(downloads: Path, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        resolve_settings(downloads, config_path=tmp_path / "nope.toml")


def test_malformed_toml_is_reported(downloads: Path) -> None:
    config = write_config(downloads / "file-organizer.toml", "[general\n")
    with pytest.raises(ConfigError, match="invalid TOML"):
        resolve_settings(downloads, config_path=config)


def test_missing_source_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        resolve_settings(tmp_path / "Missing")


def test_source_must_be_a_folder(tmp_path: Path, write_file: Any) -> None:
    file_path = write_file(tmp_path / "not-a-folder.txt")
    with pytest.raises(ConfigError, match="not a folder"):
        resolve_settings(file_path)


def test_destination_must_not_be_a_file(downloads: Path) -> None:
    (downloads / "Sorted").write_text("oops", encoding="utf-8")
    with pytest.raises(ConfigError, match="destination is not a folder"):
        resolve_settings(downloads)


def test_source_must_be_path_like(downloads: Path) -> None:
    with pytest.raises(ConfigError, match="source must be a non-empty path"):
        resolve_settings(123, config_path=None)  # type: ignore[arg-type]


def test_load_rules_does_not_require_a_source(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "custom.toml",
        """
        [general]
        source = "definitely/does/not/exist"
        default_category = "Misc"

        [categories]
        Design = [".fig"]
        """,
    )
    rules, config_path = load_rules(config)
    assert config_path == config
    assert rules.default_category == "Misc"
    assert rules.category_for_filename("file.fig") == "Design"
