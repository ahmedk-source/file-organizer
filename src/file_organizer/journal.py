"""Append-only undo journal.

Every successful move is written to a per-run JSON Lines file *before* the
command reports success.  Undo reads the file back and replays the moves in
reverse order, which is what makes the tool safe to try on a real folder.

The journal lives outside the organised folder so the user's Downloads
directory never fills up with bookkeeping files.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import JournalError
from .utils import state_directory, utc_now_iso

SCHEMA_VERSION = 1
_RUN_ID_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$")


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise JournalError(f"invalid run id: {run_id!r}")


def _new_run_id() -> str:
    # Microseconds keep ids sortable even when two runs start in one second.
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True, slots=True)
class MoveRecord:
    """One completed move, as stored in the journal."""

    run_id: str
    timestamp: str
    source: str
    destination: str
    category: str


@dataclass(frozen=True, slots=True)
class RunInfo:
    """Summary metadata for a single journal file."""

    run_id: str
    started_at: str
    source: str
    destination: str
    move_count: int
    undone: bool


class Journal:
    """Read and write run journals under a root directory."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else state_directory() / "journal"

    @property
    def root(self) -> Path:
        return self._root

    # -- writing ----------------------------------------------------------

    def begin(self, source: Path, destination: Path, run_id: str | None = None) -> str:
        """Create a journal file for a new run and return its id."""
        identifier = run_id or _new_run_id()
        _validate_run_id(identifier)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise JournalError(f"cannot create journal directory {self._root}: {error}") from error

        path = self._run_path(identifier)
        header = {
            "type": "run",
            "schema": SCHEMA_VERSION,
            "run_id": identifier,
            "started_at": utc_now_iso(),
            "source": str(source),
            "destination": str(destination),
        }
        try:
            path.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as error:
            raise JournalError(f"cannot write journal {path}: {error}") from error
        return identifier

    def record(self, record: MoveRecord) -> None:
        """Append one move to its run journal."""
        path = self._run_path(record.run_id)
        if not path.exists():
            raise JournalError(f"run {record.run_id!r} was not started")
        payload = {
            "type": "move",
            "schema": SCHEMA_VERSION,
            "run_id": record.run_id,
            "timestamp": record.timestamp,
            "source": record.source,
            "destination": record.destination,
            "category": record.category,
        }
        try:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise JournalError(f"cannot append to journal {path}: {error}") from error

    def mark_undone(self, run_id: str) -> None:
        """Mark a run as fully undone so ``--last`` does not replay it."""
        _validate_run_id(run_id)
        path = self._marker_path(run_id)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"run_id": run_id, "undone_at": utc_now_iso()}, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            raise JournalError(f"cannot mark run {run_id!r} as undone: {error}") from error

    # -- reading ----------------------------------------------------------

    def exists(self, run_id: str) -> bool:
        _validate_run_id(run_id)
        return self._run_path(run_id).is_file()

    def load(self, run_id: str) -> list[MoveRecord]:
        """Return the moves of a run in the order they were performed."""
        _validate_run_id(run_id)
        path = self._run_path(run_id)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError as error:
            raise JournalError(f"unknown run: {run_id}") from error
        except OSError as error:
            raise JournalError(f"cannot read journal {path}: {error}") from error

        records: list[MoveRecord] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # A crash can leave a truncated final line.  Losing the last
                # record is preferable to refusing to undo the remaining ones.
                continue
            if not isinstance(payload, dict) or payload.get("type") != "move":
                continue
            record = self._parse_move(payload, run_id)
            if record is not None:
                records.append(record)
        return records

    def info(self, run_id: str) -> RunInfo:
        """Return metadata for one run, raising if it does not exist."""
        _validate_run_id(run_id)
        path = self._run_path(run_id)
        if not path.is_file():
            raise JournalError(f"unknown run: {run_id}")
        info = self._read_run_info(path)
        if info is None:
            raise JournalError(f"journal for run {run_id} is corrupt")
        return info

    def runs(self) -> list[RunInfo]:
        """Return all known runs, newest first."""
        if not self._root.is_dir():
            return []
        runs: list[RunInfo] = []
        for path in self._root.glob("*.jsonl"):
            info = self._read_run_info(path)
            if info is not None:
                runs.append(info)
        runs.sort(key=lambda run: (run.started_at, run.run_id), reverse=True)
        return runs

    def latest_run_id(self, *, only_undoable: bool = True) -> str | None:
        """Return the newest run id, optionally skipping already-undone runs."""
        for run in self.runs():
            if run.undone and only_undoable:
                continue
            return run.run_id
        return None

    def is_undone(self, run_id: str) -> bool:
        _validate_run_id(run_id)
        return self._marker_path(run_id).is_file()

    # -- internals --------------------------------------------------------

    def _run_path(self, run_id: str) -> Path:
        return self._root / f"{run_id}.jsonl"

    def _marker_path(self, run_id: str) -> Path:
        return self._root / f"{run_id}.undone"

    @staticmethod
    def _parse_move(payload: dict[str, Any], run_id: str) -> MoveRecord | None:
        source = payload.get("source")
        destination = payload.get("destination")
        category = payload.get("category")
        timestamp = payload.get("timestamp")
        if not all(isinstance(value, str) and value for value in (source, destination, timestamp)):
            return None
        return MoveRecord(
            run_id=run_id,
            timestamp=str(timestamp),
            source=str(source),
            destination=str(destination),
            category=category if isinstance(category, str) else "",
        )

    def _read_run_info(self, path: Path) -> RunInfo | None:
        try:
            with path.open(encoding="utf-8") as handle:
                first_line = handle.readline()
                payload = json.loads(first_line) if first_line.strip() else {}
                if not isinstance(payload, dict) or payload.get("type") != "run":
                    return None
                move_count = 0
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and entry.get("type") == "move":
                        move_count += 1
        except (OSError, json.JSONDecodeError):
            return None

        run_id = payload.get("run_id")
        started_at = payload.get("started_at")
        source = payload.get("source")
        destination = payload.get("destination")
        if not all(
            isinstance(value, str) and value for value in (run_id, started_at, source, destination)
        ):
            return None
        return RunInfo(
            run_id=str(run_id),
            started_at=str(started_at),
            source=str(source),
            destination=str(destination),
            move_count=move_count,
            undone=self._marker_path(str(run_id)).is_file(),
        )
