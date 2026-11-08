"""Exception hierarchy used across the project.

Keeping a small, explicit hierarchy lets the CLI map failures to exit codes
without checking for built-in exception types, and gives library users a
single ``except OrganizerError`` entry point.
"""

from __future__ import annotations


class OrganizerError(Exception):
    """Base class for every error raised by file-organizer."""


class ConfigError(OrganizerError):
    """Raised when configuration is missing, malformed, or contradictory."""


class JournalError(OrganizerError):
    """Raised when the undo journal cannot be read or written safely."""
