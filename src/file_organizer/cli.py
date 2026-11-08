"""Command-line interface for file-organizer."""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from . import __version__
from .config import Settings, load_rules, resolve_settings
from .console import Console
from .errors import ConfigError, OrganizerError
from .journal import Journal, RunInfo
from .organizer import (
    Failure,
    Move,
    Organizer,
    Plan,
    RunResult,
    Skip,
    UndoResult,
    undo_run,
)
from .utils import human_size

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

_PREVIEW_LIMIT = 20

_EPILOG = """\
examples:
  file-organizer organize                  preview what would happen in ~/Downloads
  file-organizer organize --apply          actually move the files
  file-organizer organize -r --apply       include files in sub-folders
  file-organizer undo --last               preview undoing the latest run
  file-organizer undo --last --apply       put every file back
  file-organizer rules                     list the category rules in use
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="file-organizer",
        description="Sort a downloads folder into tidy, predictable category folders.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="count", default=0, help="show per-file detail")
    common.add_argument(
        "-q", "--quiet", action="store_true", help="hide the plan and progress output"
    )
    common.add_argument("--no-color", action="store_true", help="disable ANSI colour")

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    organize = subparsers.add_parser(
        "organize",
        parents=[common],
        help="sort files into category folders",
        description="Preview (default) or perform the sorting of a folder.",
    )
    organize.add_argument(
        "source", nargs="?", type=Path, help="folder to sort (default: ~/Downloads)"
    )
    organize.add_argument(
        "-d",
        "--destination",
        type=Path,
        help="where category folders are created (default: Sorted inside the source folder)",
    )
    organize.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        default=None,
        help="also sort files inside sub-folders",
    )
    organize.add_argument(
        "--on-conflict",
        choices=("rename", "skip", "overwrite"),
        default=None,
        help="what to do when a file already exists (default: rename)",
    )
    organize.add_argument(
        "--keep-hidden",
        action="store_true",
        help="include dot-files and hidden files",
    )
    organize.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="move symbolic links instead of skipping them",
    )
    organize.add_argument(
        "-c",
        "--config",
        dest="config_path",
        type=Path,
        help="path to a TOML configuration file",
    )
    mode = organize.add_mutually_exclusive_group()
    mode.add_argument("--apply", dest="dry_run", action="store_false", help="perform the moves")
    mode.add_argument(
        "--dry-run", dest="dry_run", action="store_true", help="preview only (default)"
    )
    organize.add_argument("--json", action="store_true", help="print machine-readable JSON")
    organize.set_defaults(dry_run=True, handler=_cmd_organize)

    undo = subparsers.add_parser(
        "undo",
        parents=[common],
        help="restore the files moved by a previous run",
        description="Preview (default) or perform the undo of a recorded run.",
    )
    undo.add_argument("run_id", nargs="?", help="run id shown by 'organize' and 'history'")
    undo.add_argument("--last", action="store_true", help="use the most recent run")
    undo_mode = undo.add_mutually_exclusive_group()
    undo_mode.add_argument("--apply", dest="dry_run", action="store_false", help="perform the undo")
    undo_mode.add_argument(
        "--dry-run", dest="dry_run", action="store_true", help="preview only (default)"
    )
    undo.add_argument("--json", action="store_true", help="print machine-readable JSON")
    undo.set_defaults(dry_run=True, handler=_cmd_undo)

    history = subparsers.add_parser(
        "history",
        parents=[common],
        help="list recorded runs",
        description="Show previous runs stored in the journal.",
    )
    history.add_argument("--limit", type=_positive_int, default=10, help="number of runs to show")
    history.add_argument("--json", action="store_true", help="print machine-readable JSON")
    history.set_defaults(handler=_cmd_history)

    rules = subparsers.add_parser(
        "rules",
        parents=[common],
        help="list the category rules",
        description="Show which extensions belong to which category.",
    )
    rules.add_argument(
        "-c",
        "--config",
        dest="config_path",
        type=Path,
        help="path to a TOML configuration file",
    )
    rules.add_argument("--json", action="store_true", help="print machine-readable JSON")
    rules.set_defaults(handler=_cmd_rules)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code instead of calling ``sys.exit``."""
    _enable_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(
        color=False if getattr(args, "no_color", False) else None,
        quiet=getattr(args, "quiet", False),
    )
    handler = cast(Callable[[argparse.Namespace, Console], int], args.handler)
    try:
        return handler(args, console)
    except OrganizerError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\ncancelled", file=sys.stderr)
        return EXIT_INTERRUPTED
    except BrokenPipeError:  # e.g. ``file-organizer history | head``
        return EXIT_OK


# ---------------------------------------------------------------------------
# organize
# ---------------------------------------------------------------------------


def _cmd_organize(args: argparse.Namespace, console: Console) -> int:
    settings = resolve_settings(
        source=args.source,
        destination=args.destination,
        recursive=args.recursive,
        on_conflict=args.on_conflict,
        skip_hidden=False if args.keep_hidden else None,
        follow_symlinks=True if args.follow_symlinks else None,
        config_path=args.config_path,
    )
    organizer = Organizer(settings)
    plan = organizer.plan()

    if args.json:
        if args.dry_run:
            _emit(_plan_payload(settings, plan, dry_run=True))
            return EXIT_OK
        result = organizer.execute(plan) if plan.moves else None
        _emit(_result_payload(settings, plan, result))
        return EXIT_FAILURE if result is not None and result.failed else EXIT_OK

    _print_header(console, settings, dry_run=args.dry_run)
    if not plan.moves and not plan.skipped:
        console.info("")
        console.info("Nothing to organize - the source folder is already tidy.")
        return EXIT_OK

    if plan.moves:
        _print_moves(console, plan, verbose=args.verbose > 0)
    _print_skips(console, plan.skipped, root=plan.source, verbose=args.verbose > 0)

    if args.dry_run:
        console.info("")
        if plan.moves:
            message = f"Preview only - re-run with --apply to move {len(plan.moves)} file(s)."
            console.write(console.style(message, "yellow"))
        else:
            console.write(console.style("Preview only - nothing would be moved.", "yellow"))
        return EXIT_OK

    if not plan.moves:
        console.info("")
        console.info("Nothing to move.")
        return EXIT_OK

    console.info("")
    result = organizer.execute(plan)
    if args.verbose:
        for move in result.completed:
            source = _display(move.source, plan.source)
            destination = _display(move.destination, plan.destination)
            console.write(f"  moved  {source} -> {destination}")

    summary = (
        f"Moved {len(result.completed)} file(s) ({human_size(result.moved_bytes)}) "
        f"in {result.elapsed:.2f}s."
    )
    console.write(console.style(summary, "yellow" if result.failed else "green"))
    for warning in result.warnings:
        console.write(console.style(f"warning: {warning}", "yellow"))

    _print_failures(console, result.failed, root=plan.source)

    if result.completed:
        console.info("")
        console.paragraph("Run id", result.run_id)
        command = f"file-organizer undo {result.run_id}"
        console.write(f"Undo with: {console.style(command, 'cyan')}")
    return EXIT_FAILURE if result.failed else EXIT_OK


def _print_header(console: Console, settings: Settings, *, dry_run: bool) -> None:
    if console.quiet:
        return
    console.paragraph("Source", str(settings.source))
    console.paragraph("Destination", str(settings.destination))
    console.paragraph("Mode", "preview (no files will be changed)" if dry_run else "apply")
    if settings.config_path is not None:
        console.paragraph("Config", str(settings.config_path))
    console.paragraph("Conflict", settings.on_conflict.value)


def _print_moves(console: Console, plan: Plan, *, verbose: bool) -> None:
    console.info("")
    console.info(f"Moves  {len(plan.moves)} file(s), {human_size(plan.total_bytes)}")
    ordered = sorted(plan.moves, key=lambda move: (move.category, str(move.source).casefold()))
    shown = ordered if verbose else ordered[:_PREVIEW_LIMIT]
    rows = [
        [move.category, _display(move.source, plan.source), human_size(move.size)] for move in shown
    ]
    console.table(["Category", "File", "Size"], rows, aligns=["l", "l", "r"])
    hidden = len(ordered) - len(shown)
    if hidden > 0:
        console.info(f"... and {hidden} more (use --verbose to list every file)")


def _print_skips(console: Console, skipped: Sequence[Skip], *, root: Path, verbose: bool) -> None:
    if not skipped:
        return
    console.info("")
    console.info(f"Skipped  {len(skipped)} file(s)")
    if verbose:
        rows = [[skip.reason, _display(skip.source, root)] for skip in skipped]
        console.table(["Reason", "File"], rows)
        return
    counts = Counter(skip.reason for skip in skipped)
    rows = [[reason, str(count)] for reason, count in sorted(counts.items())]
    console.table(["Reason", "Files"], rows, aligns=["l", "r"])


def _print_failures(console: Console, failures: Sequence[Failure], *, root: Path) -> None:
    if not failures:
        return
    console.info("")
    console.write(console.style(f"{len(failures)} file(s) could not be processed:", "red"))
    for failure in failures:
        console.write(f"  {_display(failure.source, root)}: {failure.reason}")


# ---------------------------------------------------------------------------
# undo
# ---------------------------------------------------------------------------


def _cmd_undo(args: argparse.Namespace, console: Console) -> int:
    journal = Journal()
    run_id: str | None = args.run_id
    if run_id is None:
        if not args.last:
            raise ConfigError("provide a RUN_ID or use --last")
        run_id = journal.latest_run_id()
        if run_id is None:
            console.info("No runs available to undo.")
            return EXIT_OK

    info = journal.info(run_id)
    result = undo_run(journal, run_id, dry_run=args.dry_run)

    if args.json:
        _emit(_undo_payload(info, result))
        return EXIT_FAILURE if result.failed else EXIT_OK

    destination_root = Path(info.destination)
    source_root = Path(info.source)
    if not console.quiet:
        console.paragraph("Run", info.run_id)
        console.paragraph("Started", _format_timestamp(info.started_at))
        console.paragraph("Source", info.source)
        console.paragraph("Destination", info.destination)

    if result.restored:
        console.info("")
        verb = "Would restore" if result.dry_run else "Restored"
        console.info(f"{verb}  {len(result.restored)} file(s)")
        shown = result.restored if args.verbose else result.restored[:_PREVIEW_LIMIT]
        rows = [
            [
                _display(move.destination, destination_root),
                _display(move.source, source_root),
            ]
            for move in shown
        ]
        console.table(["File", "Restore to"], rows)
        hidden = len(result.restored) - len(shown)
        if hidden > 0:
            console.info(f"... and {hidden} more (use --verbose to list every file)")
    else:
        console.info("")
        console.info("No files were restored.")

    _print_skips(console, result.skipped, root=destination_root, verbose=args.verbose > 0)
    _print_failures(console, result.failed, root=destination_root)

    if result.dry_run and result.restored:
        console.info("")
        console.write(
            console.style("Preview only - re-run with --apply to restore these files.", "yellow")
        )
    elif not result.failed and result.restored:
        console.info("")
        console.write(console.style("Undo complete.", "green"))
        console.info("The run is marked as undone and will be skipped by 'undo --last'.")
    return EXIT_FAILURE if result.failed else EXIT_OK


# ---------------------------------------------------------------------------
# history / rules
# ---------------------------------------------------------------------------


def _cmd_history(args: argparse.Namespace, console: Console) -> int:
    runs = Journal().runs()[: args.limit]
    if args.json:
        _emit(
            {
                "schema": 1,
                "command": "history",
                "runs": [
                    {
                        "run_id": run.run_id,
                        "started_at": run.started_at,
                        "source": run.source,
                        "destination": run.destination,
                        "moves": run.move_count,
                        "undone": run.undone,
                    }
                    for run in runs
                ],
            }
        )
        return EXIT_OK

    if not runs:
        console.info("No runs recorded yet.")
        return EXIT_OK

    rows = [
        [
            run.run_id,
            _format_timestamp(run.started_at),
            str(run.move_count),
            "undone" if run.undone else "active",
        ]
        for run in runs
    ]
    console.table(["Run ID", "Started", "Moves", "Status"], rows, aligns=["l", "l", "r", "l"])
    return EXIT_OK


def _cmd_rules(args: argparse.Namespace, console: Console) -> int:
    rules, config_path = load_rules(args.config_path)
    grouped = rules.grouped()

    if args.json:
        _emit(
            {
                "schema": 1,
                "command": "rules",
                "config": str(config_path) if config_path is not None else None,
                "default_category": rules.default_category,
                "categories": [
                    {"name": name, "extensions": list(extensions)}
                    for name, extensions in grouped.items()
                ],
            }
        )
        return EXIT_OK

    console.info(
        f"Categories ({len(grouped)}) - default: {rules.default_category}"
        + (f" - config: {config_path}" if config_path is not None else "")
    )
    console.info("")
    label_width = max(12, max(len(name) for name in grouped) + 2)
    for name, extensions in grouped.items():
        prefix = f"{name:<{label_width}}"
        if not extensions:
            console.write(f"{prefix}(no extensions - receives everything else)")
            continue
        lines = textwrap.wrap(", ".join(extensions), width=64) or [""]
        console.write(f"{prefix}{lines[0]}")
        for line in lines[1:]:
            console.write(f"{' ' * label_width}{line}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# JSON payloads
# ---------------------------------------------------------------------------


def _plan_payload(settings: Settings, plan: Plan, *, dry_run: bool) -> dict[str, Any]:
    return {
        "schema": 1,
        "command": "organize",
        "dry_run": dry_run,
        "source": str(settings.source),
        "destination": str(settings.destination),
        "config": str(settings.config_path) if settings.config_path is not None else None,
        "on_conflict": settings.on_conflict.value,
        "moves": [_move_payload(move) for move in plan.moves],
        "skipped": [_skip_payload(skip) for skip in plan.skipped],
        "totals": _totals(plan),
    }


def _result_payload(settings: Settings, plan: Plan, result: RunResult | None) -> dict[str, Any]:
    completed = result.completed if result is not None else ()
    failed = result.failed if result is not None else ()
    return {
        "schema": 1,
        "command": "organize",
        "dry_run": False,
        "run_id": result.run_id if result is not None else None,
        "source": str(settings.source),
        "destination": str(settings.destination),
        "moved": [_move_payload(move) for move in completed],
        "failed": [_failure_payload(failure) for failure in failed],
        "skipped": [_skip_payload(skip) for skip in plan.skipped],
        "warnings": list(result.warnings) if result is not None else [],
        "elapsed_seconds": round(result.elapsed, 3) if result is not None else 0.0,
    }


def _undo_payload(info: RunInfo, result: UndoResult) -> dict[str, Any]:
    return {
        "schema": 1,
        "command": "undo",
        "dry_run": result.dry_run,
        "run_id": result.run_id,
        "started_at": info.started_at,
        "source": info.source,
        "destination": info.destination,
        "restored": [_move_payload(move) for move in result.restored],
        "skipped": [_skip_payload(skip) for skip in result.skipped],
        "failed": [_failure_payload(failure) for failure in result.failed],
    }


def _move_payload(move: Move) -> dict[str, Any]:
    return {
        "source": str(move.source),
        "destination": str(move.destination),
        "category": move.category,
        "size": move.size,
    }


def _skip_payload(skip: Skip) -> dict[str, str]:
    return {"source": str(skip.source), "reason": skip.reason}


def _failure_payload(failure: Failure) -> dict[str, str]:
    return {"source": str(failure.source), "reason": failure.reason}


def _totals(plan: Plan) -> dict[str, Any]:
    return {
        "files": len(plan.moves),
        "bytes": plan.total_bytes,
        "categories": {
            name: {"files": summary.files, "bytes": summary.total_bytes}
            for name, summary in plan.by_category().items()
        },
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _format_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _enable_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            continue
