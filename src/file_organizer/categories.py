"""Extension-to-category rules.

The built-in rules cover the file types people actually receive in a Downloads
folder.  A ``RuleSet`` is immutable: user configuration produces a *new* rule
set instead of mutating a shared one, which keeps parallel runs predictable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .errors import ConfigError

DEFAULT_CATEGORY = "Other"

#: Built-in mapping of category name to the extensions it owns.  Order matters:
#: it is the order used when listing categories.
BUILTIN_CATEGORIES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "Images": (
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".webp",
            ".svg",
            ".tif",
            ".tiff",
            ".heic",
            ".heif",
            ".avif",
            ".ico",
            ".raw",
            ".cr2",
            ".nef",
            ".arw",
        ),
        "PDF": (".pdf",),
        "Documents": (
            ".doc",
            ".docx",
            ".odt",
            ".rtf",
            ".txt",
            ".md",
            ".tex",
            ".epub",
            ".mobi",
            ".xls",
            ".xlsx",
            ".ods",
            ".csv",
            ".ppt",
            ".pptx",
            ".odp",
        ),
        "Programs": (
            ".exe",
            ".msi",
            ".msix",
            ".appx",
            ".dmg",
            ".pkg",
            ".deb",
            ".rpm",
            ".appimage",
            ".apk",
            ".ipa",
            ".xapk",
        ),
        "Archives": (
            ".zip",
            ".rar",
            ".7z",
            ".tar",
            ".gz",
            ".bz2",
            ".xz",
            ".zst",
            ".tgz",
            ".iso",
            ".jar",
        ),
        "Audio": (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus", ".wma"),
        "Video": (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v", ".mpg", ".mpeg"),
        "Fonts": (".ttf", ".otf", ".woff", ".woff2"),
        "Code": (
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".html",
            ".css",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".sql",
            ".sh",
            ".ps1",
            ".bat",
            ".cmd",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".cs",
            ".go",
            ".rs",
            ".rb",
            ".php",
        ),
    }
)

#: Names Windows refuses to use for files or folders.
_RESERVED_WINDOWS_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)
_INVALID_NAME_CHARACTERS = frozenset('<>:"/\\|?*')


def validate_category_name(name: str) -> None:
    """Validate a category name and raise :class:`ConfigError` when invalid.

    Category names become folder names, so they are checked against the lowest
    common denominator: rules that work on Windows, macOS and Linux alike.
    """
    if not isinstance(name, str):
        raise ConfigError("category names must be strings")
    stripped = name.strip()
    if not stripped:
        raise ConfigError("category names must not be empty")
    if stripped != name:
        raise ConfigError(f"category {name!r} must not start or end with whitespace")
    if name in {".", ".."}:
        raise ConfigError(f"{name!r} is not a valid category name")
    if any(character in _INVALID_NAME_CHARACTERS for character in name):
        raise ConfigError(
            f"category {name!r} contains a character that is not allowed in folder names"
        )
    if any(ord(character) < 32 for character in name):
        raise ConfigError(f"category {name!r} contains a control character")
    if name.endswith("."):
        raise ConfigError(f"category {name!r} must not end with a dot")
    if name.casefold() in _RESERVED_WINDOWS_NAMES:
        raise ConfigError(f"category {name!r} is a reserved name on Windows")


def normalise_extension(raw: Any) -> str:
    """Return a lower-case, dot-prefixed extension or raise :class:`ConfigError`."""
    if not isinstance(raw, str):
        raise ConfigError("extensions must be strings")
    extension = raw.strip().lower()
    if not extension:
        raise ConfigError("extensions must not be empty")
    if extension.startswith("*."):
        extension = extension[1:]
    if not extension.startswith("."):
        extension = f".{extension}"
    if extension == "." or len(extension) < 2:
        raise ConfigError(f"invalid extension {raw!r}")
    if any(character in extension for character in ' /\\<>:"|?*'):
        raise ConfigError(f"invalid extension {raw!r}")
    return extension


@dataclass(frozen=True, slots=True)
class RuleSet:
    """An immutable, validated extension-to-category mapping."""

    _extension_map: Mapping[str, str]
    _category_order: tuple[str, ...]
    default_category: str = DEFAULT_CATEGORY

    def __post_init__(self) -> None:
        if not self._category_order:
            raise ConfigError("at least one category is required")
        if len(set(self._category_order)) != len(self._category_order):
            raise ConfigError("category names must be unique")
        for category in self._category_order:
            validate_category_name(category)
        validate_category_name(self.default_category)
        if self.default_category not in self._category_order:
            raise ConfigError(f"default category {self.default_category!r} is not defined")
        for extension, category in self._extension_map.items():
            if extension != extension.lower() or not extension.startswith("."):
                raise ConfigError(f"extension {extension!r} is not normalised")
            if category not in self._category_order:
                raise ConfigError(
                    f"extension {extension!r} belongs to an unknown category {category!r}"
                )

    # -- construction -----------------------------------------------------

    @classmethod
    def builtin(cls, default_category: str = DEFAULT_CATEGORY) -> RuleSet:
        """Return the built-in rule set."""
        return cls._create(BUILTIN_CATEGORIES, default_category=default_category)

    @classmethod
    def _create(cls, categories: Mapping[str, Iterable[str]], *, default_category: str) -> RuleSet:
        extension_map: dict[str, str] = {}
        order: list[str] = []
        for category, raw_extensions in categories.items():
            extensions = list(raw_extensions)
            if not extensions:
                continue
            validate_category_name(category)
            if category in order:
                raise ConfigError(f"duplicate category {category!r}")
            order.append(category)
            for raw_extension in extensions:
                extension = normalise_extension(raw_extension)
                owner = extension_map.get(extension)
                if owner is not None and owner != category:
                    raise ConfigError(
                        f"extension {extension!r} is assigned to both {owner!r} and {category!r}"
                    )
                extension_map[extension] = category
        if default_category not in order:
            order.append(default_category)
        return cls(MappingProxyType(extension_map), tuple(order), default_category)

    # -- queries ----------------------------------------------------------

    @property
    def category_order(self) -> tuple[str, ...]:
        """Category names in their configured order."""
        return self._category_order

    def category_for_filename(self, filename: str) -> str:
        """Return the category that owns *filename*.

        Two-part extensions such as ``.tar.gz`` are honoured so that a user can
        target them explicitly from configuration.
        """
        lowered = filename.lower()
        parts = lowered.rsplit(".", 2)
        if len(parts) == 3 and f".{parts[1]}.{parts[2]}" in self._extension_map:
            return self._extension_map[f".{parts[1]}.{parts[2]}"]
        suffix = Path(lowered).suffix
        return self._extension_map.get(suffix, self.default_category)

    def grouped(self) -> dict[str, tuple[str, ...]]:
        """Return ``category -> sorted extensions`` for display purposes."""
        grouped: dict[str, list[str]] = {category: [] for category in self._category_order}
        for extension, category in self._extension_map.items():
            grouped[category].append(extension)
        return {category: tuple(sorted(extensions)) for category, extensions in grouped.items()}

    def with_overrides(
        self,
        overrides: Mapping[str, Iterable[str]],
        *,
        default_category: str | None = None,
        replace_defaults: bool = False,
    ) -> RuleSet:
        """Return a new rule set with user-supplied categories applied.

        User assignments always win over built-in ones, which is what allows
        moving an extension (say ``.pdf``) into a custom category.  Assigning
        the same extension to two *user* categories is rejected as ambiguous.
        """
        target_default = self.default_category if default_category is None else default_category
        user_map: dict[str, str] = {}
        for category, raw_extensions in overrides.items():
            validate_category_name(category)
            extensions = [normalise_extension(item) for item in raw_extensions]
            if not extensions:
                raise ConfigError(f"category {category!r} must declare at least one extension")
            for extension in extensions:
                owner = user_map.get(extension)
                if owner is not None and owner != category:
                    raise ConfigError(
                        f"extension {extension!r} is assigned to both {owner!r} and {category!r}"
                    )
                user_map[extension] = category

        base_map: dict[str, str] = {} if replace_defaults else dict(self._extension_map)
        base_order: list[str] = [] if replace_defaults else list(self._category_order)
        base_map.update(user_map)

        order = [
            category
            for category in base_order
            if category == target_default or category in base_map.values()
        ]
        for category in overrides:
            if category not in order:
                order.append(category)
        if target_default not in order:
            order.append(target_default)

        categories = {
            category: [extension for extension, owner in base_map.items() if owner == category]
            for category in order
        }
        return RuleSet._create(categories, default_category=target_default)
