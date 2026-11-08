"""File Organizer: a safe, reversible sorter for the Downloads folder.

The public API mirrors the CLI: build :class:`Settings`, create an
:class:`Organizer`, call :meth:`Organizer.plan` for a dry run and
:meth:`Organizer.execute` to perform the moves.  Every run can be reverted
with :func:`undo_run`.
"""

from __future__ import annotations

from .categories import BUILTIN_CATEGORIES, DEFAULT_CATEGORY, RuleSet
from .config import (
    ConflictPolicy,
    Settings,
    load_rules,
    resolve_settings,
)
from .errors import ConfigError, JournalError, OrganizerError
from .journal import Journal, MoveRecord, RunInfo
from .organizer import (
    CategorySummary,
    Failure,
    Move,
    Organizer,
    Plan,
    RunResult,
    Skip,
    UndoResult,
    undo_run,
)

__version__ = "1.0.0"

__all__ = [
    "BUILTIN_CATEGORIES",
    "DEFAULT_CATEGORY",
    "CategorySummary",
    "ConfigError",
    "ConflictPolicy",
    "Failure",
    "Journal",
    "JournalError",
    "Move",
    "MoveRecord",
    "Organizer",
    "OrganizerError",
    "Plan",
    "RuleSet",
    "RunInfo",
    "RunResult",
    "Settings",
    "Skip",
    "UndoResult",
    "__version__",
    "load_rules",
    "resolve_settings",
    "undo_run",
]
