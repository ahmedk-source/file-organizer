"""Small, dependency-free helpers shared by the rest of the package."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

#: Files a browser writes while a download is still in progress.  They must
#: never be moved: doing so corrupts the download in most browsers.
PARTIAL_DOWNLOAD_SUFFIXES: frozenset[str] = frozenset(
    {
        ".aria2",
        ".crdownload",
        ".download",
        ".opdownload",
        ".part",
        ".partial",
        ".temp",
        ".tmp",
        ".!ut",
    }
)

_HASH_CHUNK_SIZE = 1024 * 1024
_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def utc_now_iso() -> str:
    """Return the current UTC time as a second-precision ISO-8601 string."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def state_directory() -> Path:
    """Return the per-user directory where journals and undo data live.

    The location follows each platform's conventions and can be overridden
    with the ``FILE_ORGANIZER_STATE_DIR`` environment variable, which is also
    what the test-suite uses to stay hermetic.
    """
    override = os.environ.get("FILE_ORGANIZER_STATE_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "file-organizer"


def is_hidden(path: Path) -> bool:
    """Return ``True`` for dot-files and Windows hidden files."""
    if path.name.startswith("."):
        return True
    try:
        attributes = getattr(path.stat(), "st_file_attributes", None)
    except OSError:
        return False
    if attributes is None:
        return False
    hidden_flag = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2)
    return bool(attributes & hidden_flag)


def is_partial_download(path: Path) -> bool:
    """Return ``True`` if *path* looks like an in-progress download."""
    return path.suffix.lower() in PARTIAL_DOWNLOAD_SUFFIXES


def sha256_of(path: Path) -> str:
    """Return the hexadecimal SHA-256 digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def same_content(first: Path, second: Path) -> bool:
    """Return ``True`` when both paths hold byte-identical regular files."""
    try:
        if first.stat().st_size != second.stat().st_size:
            return False
        return sha256_of(first) == sha256_of(second)
    except OSError:
        return False


def human_size(num_bytes: int) -> str:
    """Format a byte count using binary units, e.g. ``1.4 MB``."""
    if num_bytes < 0:
        raise ValueError("num_bytes must not be negative")
    size = float(num_bytes)
    for unit in _SIZE_UNITS:
        if size < 1024 or unit == _SIZE_UNITS[-1]:
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")  # pragma: no cover


def describe_error(error: BaseException) -> str:
    """Return a short, human-readable description of an exception."""
    message = str(error).strip()
    return message or type(error).__name__
