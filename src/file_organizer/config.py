"""Configuration loading and validation.

Priority is always: command-line flag > TOML config file > built-in default.
Everything is validated up-front so a typo in the config file produces one
clear error instead of silently doing the wrong thing to the user's files.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .categories import DEFAULT_CATEGORY, RuleSet, validate_category_name
from .errors import ConfigError


class ConflictPolicy(StrEnum):
    """What to do when a file with the same name already exists."""

    RENAME = "rename"
    SKIP = "skip"
    OVERWRITE = "overwrite"


DEFAULT_DESTINATION = "Sorted"
CONFIG_FILENAME = "file-organizer.toml"

_GENERAL_KEYS = frozenset(
    {
        "source",
        "destination",
        "recursive",
        "on_conflict",
        "skip_hidden",
        "follow_symlinks",
        "default_category",
        "replace_default_categories",
    }
)
_TOP_LEVEL_KEYS = frozenset({"general", "categories"})


@dataclass(frozen=True, slots=True)
class Settings:
    """Fully resolved, validated settings for one run."""

    source: Path
    destination: Path
    recursive: bool = False
    on_conflict: ConflictPolicy = ConflictPolicy.RENAME
    skip_hidden: bool = True
    follow_symlinks: bool = False
    rules: RuleSet = field(default_factory=RuleSet.builtin)
    config_path: Path | None = None


def default_source() -> Path:
    """Return the platform's default Downloads folder."""
    return Path.home() / "Downloads"


def discover_config(explicit: Path | None = None) -> Path | None:
    """Find the config file to use, or ``None`` when there is none."""
    if explicit is not None:
        path = explicit.expanduser()
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path
    candidates = (Path.cwd() / CONFIG_FILENAME, Path.home() / f".{CONFIG_FILENAME}")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_config_file(path: Path) -> dict[str, Any]:
    """Parse a TOML config file and validate its structure."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ConfigError(f"cannot read config file {path}: {error}") from error
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"invalid TOML in {path}: {error}") from error

    unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ConfigError(
            f"unknown top-level key(s) in {path}: {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(_TOP_LEVEL_KEYS))})"
        )
    general = data.get("general", {})
    if not isinstance(general, dict):
        raise ConfigError("[general] must be a table")
    unknown_general = sorted(set(general) - _GENERAL_KEYS)
    if unknown_general:
        raise ConfigError(
            f"unknown key(s) in [general]: {', '.join(unknown_general)} "
            f"(allowed: {', '.join(sorted(_GENERAL_KEYS))})"
        )
    categories = data.get("categories", {})
    if not isinstance(categories, dict):
        raise ConfigError("[categories] must be a table of category -> extension list")
    for name, extensions in categories.items():
        if not isinstance(extensions, list) or not all(
            isinstance(item, str) for item in extensions
        ):
            raise ConfigError(f"category {name!r} must be a list of extensions")
    return data


def load_rules(config_path: Path | str | None = None) -> tuple[RuleSet, Path | None]:
    """Load only the category rules, without touching or validating a source folder."""
    explicit = Path(config_path).expanduser() if config_path is not None else None
    resolved = discover_config(explicit)
    data = load_config_file(resolved) if resolved is not None else {}
    return _rules_from_values(data), resolved


def _rules_from_values(file_values: Mapping[str, Any]) -> RuleSet:
    general = file_values.get("general", {})
    default_category = general.get("default_category", DEFAULT_CATEGORY)
    if not isinstance(default_category, str):
        raise ConfigError("default_category must be a string")
    validate_category_name(default_category)
    replace_defaults = _flag(
        general, "replace_default_categories", False, "replace_default_categories"
    )
    return RuleSet.builtin(default_category).with_overrides(
        file_values.get("categories", {}),
        default_category=default_category,
        replace_defaults=replace_defaults,
    )


def resolve_settings(
    source: Path | str | None = None,
    *,
    destination: Path | str | None = None,
    recursive: bool | None = None,
    on_conflict: str | ConflictPolicy | None = None,
    skip_hidden: bool | None = None,
    follow_symlinks: bool | None = None,
    config_path: Path | str | None = None,
) -> Settings:
    """Merge CLI arguments, config file values and defaults into ``Settings``.

    Relative ``source`` paths are resolved against the config file's folder
    (or the current working directory when there is no config file), while a
    relative ``destination`` is resolved against the source folder, so
    ``destination = "Sorted"`` means "a Sorted folder inside Downloads".
    """
    explicit_config = Path(config_path).expanduser() if config_path is not None else None
    resolved_config = discover_config(explicit_config)
    file_values: dict[str, Any] = {}
    base_for_source = Path.cwd()
    if resolved_config is not None:
        file_values = load_config_file(resolved_config)
        base_for_source = resolved_config.parent

    general = file_values.get("general", {})

    if source is not None:
        source_path = _resolve_path(_expect_path_like(source, "source"), base=Path.cwd())
    else:
        source_value = general.get("source", default_source())
        source_path = _resolve_path(_expect_path_like(source_value, "source"), base=base_for_source)
    if not source_path.exists():
        raise ConfigError(f"source folder does not exist: {source_path}")
    if not source_path.is_dir():
        raise ConfigError(f"source is not a folder: {source_path}")

    destination_value = (
        destination if destination is not None else general.get("destination", DEFAULT_DESTINATION)
    )
    destination_path = _resolve_path(
        _expect_path_like(destination_value, "destination"), base=source_path
    )
    if destination_path.exists() and not destination_path.is_dir():
        raise ConfigError(f"destination is not a folder: {destination_path}")

    policy = _coerce_policy(
        on_conflict
        if on_conflict is not None
        else general.get("on_conflict", ConflictPolicy.RENAME)
    )
    rules = _rules_from_values(file_values)

    return Settings(
        source=source_path,
        destination=destination_path,
        recursive=_flag(general, "recursive", False, "recursive")
        if recursive is None
        else recursive,
        on_conflict=policy,
        skip_hidden=_flag(general, "skip_hidden", True, "skip_hidden")
        if skip_hidden is None
        else skip_hidden,
        follow_symlinks=(
            _flag(general, "follow_symlinks", False, "follow_symlinks")
            if follow_symlinks is None
            else follow_symlinks
        ),
        rules=rules,
        config_path=resolved_config,
    )


def _resolve_path(value: str | Path, *, base: Path) -> Path:
    expanded = Path(os.path.expandvars(str(value))).expanduser()
    if not expanded.is_absolute():
        expanded = base / expanded
    return expanded.resolve()


def _expect_path_like(value: object, key: str) -> str | Path:
    if isinstance(value, (str, Path)) and str(value).strip():
        return value
    raise ConfigError(f"{key} must be a non-empty path")


def _flag(values: Mapping[str, Any], key: str, default: bool, label: str) -> bool:
    value = values.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{label} must be true or false")
    return value


def _coerce_policy(value: object) -> ConflictPolicy:
    if isinstance(value, ConflictPolicy):
        return value
    if isinstance(value, str):
        try:
            return ConflictPolicy(value.strip().lower())
        except ValueError:
            allowed = ", ".join(policy.value for policy in ConflictPolicy)
            raise ConfigError(f"on_conflict must be one of {allowed}; got {value!r}") from None
    raise ConfigError("on_conflict must be a string")
