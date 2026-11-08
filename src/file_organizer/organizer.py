"""Planning and execution engine.

The two phases are deliberately separated:

``plan()``    reads the source folder and decides where every file *would* go.
``execute()`` performs a previously computed plan and journals every move.

That split is what makes ``--dry-run`` trustworthy: the preview is produced by
exactly the same code path that later performs the work.
"""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .config import ConflictPolicy, Settings
from .errors import OrganizerError
from .journal import Journal, MoveRecord
from .utils import (
    describe_error,
    is_hidden,
    is_partial_download,
    same_content,
    state_directory,
    utc_now_iso,
)


@dataclass(frozen=True, slots=True)
class Move:
    """A single file move from the source folder into a category folder."""

    source: Path
    destination: Path
    category: str
    size: int


@dataclass(frozen=True, slots=True)
class Skip:
    """A file that was deliberately left alone, with the reason why."""

    source: Path
    reason: str


@dataclass(frozen=True, slots=True)
class Failure:
    """A file whose move could not be completed."""

    source: Path
    reason: str


@dataclass(frozen=True, slots=True)
class CategorySummary:
    """Aggregated file count and size for one category."""

    category: str
    files: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class Plan:
    """The complete, immutable result of scanning a source folder."""

    source: Path
    destination: Path
    moves: tuple[Move, ...]
    skipped: tuple[Skip, ...]

    @property
    def total_bytes(self) -> int:
        return sum(move.size for move in self.moves)

    def by_category(self) -> dict[str, CategorySummary]:
        """Return one summary per category that has at least one move."""
        totals: dict[str, list[int]] = {}
        for move in self.moves:
            bucket = totals.setdefault(move.category, [0, 0])
            bucket[0] += 1
            bucket[1] += move.size
        return {
            category: CategorySummary(category, files, size)
            for category, (files, size) in sorted(totals.items())
        }


@dataclass(frozen=True, slots=True)
class RunResult:
    """Outcome of executing a plan."""

    run_id: str
    completed: tuple[Move, ...]
    failed: tuple[Failure, ...]
    skipped: tuple[Skip, ...]
    warnings: tuple[str, ...]
    elapsed: float

    @property
    def moved_bytes(self) -> int:
        return sum(move.size for move in self.completed)


@dataclass(frozen=True, slots=True)
class UndoResult:
    """Outcome of an undo operation (real or previewed)."""

    run_id: str
    restored: tuple[Move, ...]
    skipped: tuple[Skip, ...]
    failed: tuple[Failure, ...]
    dry_run: bool


class Organizer:
    """Plan and execute moves for one :class:`Settings` object."""

    def __init__(self, settings: Settings, journal: Journal | None = None) -> None:
        self._settings = settings
        self._journal = journal

    @property
    def settings(self) -> Settings:
        return self._settings

    # -- planning ---------------------------------------------------------

    def plan(self) -> Plan:
        """Scan the source folder and decide what to move where."""
        moves: list[Move] = []
        skipped: list[Skip] = []
        reserved: set[str] = set()

        for path in self._iter_paths():
            if not path.is_file():
                continue
            reason = self._skip_reason(path)
            if reason is not None:
                skipped.append(Skip(path, reason))
                continue
            category = self._settings.rules.category_for_filename(path.name)
            outcome = self._plan_one(path, category, reserved)
            if isinstance(outcome, Skip):
                skipped.append(outcome)
            else:
                moves.append(outcome)

        return Plan(
            source=self._settings.source,
            destination=self._settings.destination,
            moves=tuple(moves),
            skipped=tuple(skipped),
        )

    def _iter_paths(self) -> Iterator[Path]:
        source = self._settings.source
        excluded_roots: list[Path] = []
        for candidate in (self._settings.destination, state_directory()):
            if candidate != source and candidate.is_relative_to(source):
                excluded_roots.append(candidate)

        entries = source.rglob("*") if self._settings.recursive else source.iterdir()
        for path in sorted(
            entries, key=lambda item: (str(item.parent).casefold(), item.name.casefold())
        ):
            if any(root == path or root in path.parents for root in excluded_roots):
                continue
            yield path

    def _skip_reason(self, path: Path) -> str | None:
        if path.is_symlink() and not self._settings.follow_symlinks:
            return "symbolic link"
        if self._settings.skip_hidden and is_hidden(path):
            return "hidden file"
        if is_partial_download(path):
            return "incomplete download"
        return None

    def _plan_one(self, source: Path, category: str, reserved: set[str]) -> Move | Skip:
        target = self._settings.destination / category / source.name
        if _path_key(target) == _path_key(source):
            return Skip(source, "already in the right place")
        if target.exists() and target.is_dir():
            return Skip(source, "a folder already exists at the destination")

        policy = self._settings.on_conflict
        taken = _path_key(target) in reserved
        if target.exists() or taken:
            if policy is ConflictPolicy.SKIP:
                return Skip(source, "destination already exists")
            if policy is ConflictPolicy.RENAME:
                if target.exists() and same_content(source, target):
                    return Skip(source, "identical file already exists")
                target = self._free_name(target, reserved)
            elif taken:
                # ``overwrite`` must never destroy a file planned moments ago.
                target = self._free_name(target, reserved)

        reserved.add(_path_key(target))
        return Move(source=source, destination=target, category=category, size=_safe_size(source))

    @staticmethod
    def _free_name(target: Path, reserved: set[str]) -> Path:
        counter = 1
        while True:
            candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
            if not candidate.exists() and _path_key(candidate) not in reserved:
                return candidate
            counter += 1

    # -- execution --------------------------------------------------------

    def execute(
        self,
        plan: Plan,
        *,
        on_move: Callable[[Move], None] | None = None,
    ) -> RunResult:
        """Perform every move in *plan*, journaling each success."""
        journal = self._journal if self._journal is not None else Journal()
        run_id = journal.begin(plan.source, plan.destination)
        started = time.perf_counter()
        completed: list[Move] = []
        failed: list[Failure] = []
        warnings: list[str] = []

        for move in plan.moves:
            try:
                move.destination.parent.mkdir(parents=True, exist_ok=True)
                if (
                    self._settings.on_conflict is ConflictPolicy.OVERWRITE
                    and move.destination.exists()
                ):
                    if move.destination.is_dir():
                        raise IsADirectoryError(f"destination is a folder: {move.destination}")
                    move.destination.unlink()
                shutil.move(os.fspath(move.source), os.fspath(move.destination))
            except OSError as error:
                failed.append(Failure(move.source, describe_error(error)))
                continue

            completed.append(move)
            try:
                journal.record(
                    MoveRecord(
                        run_id=run_id,
                        timestamp=utc_now_iso(),
                        source=str(move.source),
                        destination=str(move.destination),
                        category=move.category,
                    )
                )
            except OrganizerError as error:
                warnings.append(f"could not journal {move.source.name}: {describe_error(error)}")
            if on_move is not None:
                on_move(move)

        return RunResult(
            run_id=run_id,
            completed=tuple(completed),
            failed=tuple(failed),
            skipped=plan.skipped,
            warnings=tuple(warnings),
            elapsed=time.perf_counter() - started,
        )


def undo_run(journal: Journal, run_id: str, *, dry_run: bool = False) -> UndoResult:
    """Replay a run in reverse, restoring files to their original paths."""
    info = journal.info(run_id)
    records = journal.load(run_id)
    destination_root = Path(info.destination)
    restored: list[Move] = []
    skipped: list[Skip] = []
    failed: list[Failure] = []
    retryable_skip = False

    for record in reversed(records):
        destination = Path(record.destination)
        source = Path(record.source)
        move = Move(
            source=source,
            destination=destination,
            category=record.category,
            size=_safe_size(destination),
        )
        if not destination.exists():
            skipped.append(Skip(destination, "file no longer exists"))
            continue
        if source.exists():
            skipped.append(Skip(destination, f"original location is occupied: {source}"))
            retryable_skip = True
            continue
        if dry_run:
            restored.append(move)
            continue
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(os.fspath(destination), os.fspath(source))
        except OSError as error:
            failed.append(Failure(destination, describe_error(error)))
        else:
            restored.append(move)
            _prune_empty_directories(destination.parent, stop=destination_root)

    # A run stays "active" when some files could not be restored yet, so the
    # user can resolve the conflict and retry with the same run id.
    if not dry_run and not failed and not retryable_skip and records:
        journal.mark_undone(run_id)
    return UndoResult(
        run_id=run_id,
        restored=tuple(restored),
        skipped=tuple(skipped),
        failed=tuple(failed),
        dry_run=dry_run,
    )


def _path_key(path: Path) -> str:
    """Return a case-insensitive comparison key for a path.

    Windows and macOS use case-insensitive filesystems by default, so two names
    that differ only in case are the same file there.  Treating them as equal
    on every platform is deliberately conservative.
    """
    return os.path.normcase(str(path)).casefold()


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _prune_empty_directories(start: Path, *, stop: Path) -> None:
    """Remove now-empty category folders, never the destination root itself."""
    current = start
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
