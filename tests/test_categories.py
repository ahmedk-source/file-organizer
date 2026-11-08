"""Tests for the extension-to-category rules."""

from __future__ import annotations

from typing import Any

import pytest

from file_organizer import ConfigError, RuleSet
from file_organizer.categories import DEFAULT_CATEGORY, normalise_extension


def test_builtin_rules_cover_the_common_cases() -> None:
    rules = RuleSet.builtin()
    assert rules.default_category == DEFAULT_CATEGORY
    assert rules.category_for_filename("holiday.JPG") == "Images"
    assert rules.category_for_filename("invoice.pdf") == "PDF"
    assert rules.category_for_filename("setup.exe") == "Programs"
    assert rules.category_for_filename("backup.tar.gz") == "Archives"
    assert rules.category_for_filename("song.mp3") == "Audio"
    assert rules.category_for_filename("design.psd") == DEFAULT_CATEGORY


def test_dotfiles_and_extensionless_files_fall_back_to_default() -> None:
    rules = RuleSet.builtin()
    assert rules.category_for_filename(".gitignore") == DEFAULT_CATEGORY
    assert rules.category_for_filename("LICENSE") == DEFAULT_CATEGORY
    assert rules.category_for_filename("file.") == DEFAULT_CATEGORY


def test_category_order_is_stable_and_includes_the_default() -> None:
    rules = RuleSet.builtin("Misc")
    assert rules.category_order[0] == "Images"
    assert rules.category_order[-1] == "Misc"
    grouped = rules.grouped()
    assert grouped["Misc"] == ()
    assert grouped["PDF"] == (".pdf",)


def test_overrides_can_add_a_category() -> None:
    rules = RuleSet.builtin().with_overrides({"Design": ["fig", ".sketch"]})
    assert rules.category_for_filename("mockup.fig") == "Design"
    assert rules.category_for_filename("mockup.sketch") == "Design"
    assert "Design" in rules.grouped()


def test_overrides_can_move_a_builtin_extension() -> None:
    rules = RuleSet.builtin().with_overrides({"Paperwork": [".pdf"]})
    assert rules.category_for_filename("invoice.pdf") == "Paperwork"
    assert "PDF" not in rules.grouped()


def test_compound_extension_can_be_targeted_explicitly() -> None:
    rules = RuleSet.builtin().with_overrides({"Backups": [".tar.gz"]})
    assert rules.category_for_filename("backup.tar.gz") == "Backups"


def test_replace_defaults_starts_from_an_empty_rule_set() -> None:
    rules = RuleSet.builtin().with_overrides(
        {"Only": [".mine"]}, replace_defaults=True, default_category="Other"
    )
    assert rules.grouped() == {"Only": (".mine",), "Other": ()}
    assert rules.category_for_filename("photo.jpg") == "Other"


def test_duplicate_user_assignment_is_rejected() -> None:
    with pytest.raises(ConfigError, match="assigned to both"):
        RuleSet.builtin().with_overrides({"A": [".png"], "B": [".png"]})


def test_category_without_extensions_is_rejected() -> None:
    with pytest.raises(ConfigError, match="at least one extension"):
        RuleSet.builtin().with_overrides({"Empty": []})


@pytest.mark.parametrize(
    "name",
    ["", " padded ", ".", "..", "CON", "con", "a/b", "a:b", "bad.", "tab\tname"],
)
def test_invalid_category_names_are_rejected(name: str) -> None:
    with pytest.raises(ConfigError):
        RuleSet.builtin().with_overrides({name: [".x"]})


@pytest.mark.parametrize("extension", ["", " ", ".", "a/b", "with space", 5, None])
def test_invalid_extensions_are_rejected(extension: Any) -> None:
    with pytest.raises(ConfigError):
        RuleSet.builtin().with_overrides({"Broken": [extension]})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("JPG", ".jpg"), ("*.png", ".png"), (".Tar.Gz", ".tar.gz"), ("woff2", ".woff2")],
)
def test_extension_normalisation(raw: str, expected: str) -> None:
    assert normalise_extension(raw) == expected
