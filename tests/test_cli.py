"""End-to-end tests for the command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from file_organizer.cli import main


def run(argv: list[str], capsys: Any) -> tuple[int, str, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_version_flag(capsys: Any) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "file-organizer 1.0.0" in capsys.readouterr().out


def test_rules_lists_categories(capsys: Any) -> None:
    code, out, err = run(["rules"], capsys)
    assert code == 0
    assert err == ""
    assert "Images" in out
    assert "default: Other" in out


def test_rules_json(capsys: Any) -> None:
    code, out, _ = run(["rules", "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["schema"] == 1
    assert payload["default_category"] == "Other"
    names = {item["name"] for item in payload["categories"]}
    assert {"Images", "PDF", "Programs"} <= names


def test_organize_previews_without_touching_files(
    downloads: Path, write_file: Any, capsys: Any
) -> None:
    write_file(downloads / "photo.jpg")
    write_file(downloads / "invoice.pdf")

    code, out, _ = run(["organize", str(downloads)], capsys)

    assert code == 0
    assert "Preview only" in out
    assert "photo.jpg" in out
    assert (downloads / "photo.jpg").exists()
    assert not (downloads / "Sorted").exists()


def test_organize_apply_moves_files(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / "photo.jpg")
    write_file(downloads / "invoice.pdf")

    code, out, _ = run(["organize", str(downloads), "--apply"], capsys)

    assert code == 0
    assert "Moved 2 file(s)" in out
    assert "Undo with:" in out
    assert (downloads / "Sorted" / "Images" / "photo.jpg").exists()
    assert (downloads / "Sorted" / "PDF" / "invoice.pdf").exists()


def test_organize_json_preview(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / "photo.jpg")

    code, out, _ = run(["organize", str(downloads), "--json"], capsys)

    payload = json.loads(out)
    assert code == 0
    assert payload["schema"] == 1
    assert payload["dry_run"] is True
    assert payload["moves"][0]["category"] == "Images"
    assert payload["totals"]["files"] == 1


def test_organize_json_apply(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / "photo.jpg")

    code, out, _ = run(["organize", str(downloads), "--apply", "--json"], capsys)

    payload = json.loads(out)
    assert code == 0
    assert payload["dry_run"] is False
    assert payload["run_id"]
    assert len(payload["moved"]) == 1
    assert payload["failed"] == []


def test_organise_json_apply_on_an_empty_folder(downloads: Path, capsys: Any) -> None:
    code, out, _ = run(["organize", str(downloads), "--apply", "--json"], capsys)

    payload = json.loads(out)
    assert code == 0
    assert payload["run_id"] is None
    assert payload["moved"] == []


def test_organize_reports_failures_with_exit_code_one(
    downloads: Path, write_file: Any, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_file(downloads / "photo.jpg")
    write_file(downloads / "notes.txt")

    def failing_move(source: str, destination: str) -> str:
        if Path(source).name == "notes.txt":
            raise PermissionError("locked")
        return source

    monkeypatch.setattr("file_organizer.organizer.shutil.move", failing_move)

    code, out, _ = run(["organize", str(downloads), "--apply"], capsys)

    assert code == 1
    assert "1 file(s) could not be processed" in out


def test_organize_is_idempotent(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / "photo.jpg")
    run(["organize", str(downloads), "--apply"], capsys)

    code, out, _ = run(["organize", str(downloads)], capsys)

    assert code == 0
    assert "already tidy" in out


def test_organize_empty_folder(downloads: Path, capsys: Any) -> None:
    code, out, _ = run(["organize", str(downloads)], capsys)
    assert code == 0
    assert "already tidy" in out


def test_quiet_hides_the_plan(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / "photo.jpg")

    code, out, _ = run(["organize", str(downloads), "-q"], capsys)

    assert code == 0
    assert "Source" not in out
    assert "Preview only" in out


def test_verbose_lists_every_move(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / "photo.jpg")

    _, out, _ = run(["organize", str(downloads), "--apply", "-v"], capsys)

    assert "moved  photo.jpg" in out


def test_missing_source_is_a_usage_error(tmp_path: Path, capsys: Any) -> None:
    code, _, err = run(["organize", str(tmp_path / "missing")], capsys)
    assert code == 2
    assert "does not exist" in err


def test_invalid_config_is_a_usage_error(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(Path.cwd() / "file-organizer.toml", '[general]\nrecursive = "yes"\n')
    write_file(downloads / "photo.jpg")

    code, _, err = run(["organize", str(downloads)], capsys)

    assert code == 2
    assert "recursive must be true or false" in err


def test_config_file_categories_are_used(downloads: Path, write_file: Any, capsys: Any) -> None:
    config = write_file(
        downloads / "custom.toml",
        '[categories]\nDesign = [".fig", ".sketch"]\n',
    )
    write_file(downloads / "mockup.fig")

    code, _, _ = run(["organize", str(downloads), "-c", str(config), "--apply"], capsys)

    assert code == 0
    assert (downloads / "Sorted" / "Design" / "mockup.fig").exists()


def test_keep_hidden_flag(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / ".secret.txt")

    code, _, _ = run(["organize", str(downloads), "--keep-hidden", "--apply"], capsys)

    assert code == 0
    assert (downloads / "Sorted" / "Documents" / ".secret.txt").exists()


def test_conflict_policy_can_be_selected(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / "Sorted" / "Images" / "photo.jpg", b"old")
    write_file(downloads / "photo.jpg", b"new")

    code, out, _ = run(["organize", str(downloads), "--on-conflict", "skip", "--apply"], capsys)

    assert code == 0
    assert "Skipped" in out
    assert (downloads / "photo.jpg").exists()


def test_undo_preview_then_apply(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / "photo.jpg")
    run(["organize", str(downloads), "--apply"], capsys)

    code, out, _ = run(["undo", "--last"], capsys)
    assert code == 0
    assert "Would restore" in out
    assert not (downloads / "photo.jpg").exists()

    code, out, _ = run(["undo", "--last", "--apply"], capsys)
    assert code == 0
    assert "Restored" in out
    assert (downloads / "photo.jpg").exists()


def test_undo_json(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / "photo.jpg")
    run(["organize", str(downloads), "--apply"], capsys)

    code, out, _ = run(["undo", "--last", "--json"], capsys)

    payload = json.loads(out)
    assert code == 0
    assert payload["dry_run"] is True
    assert len(payload["restored"]) == 1


def test_undo_without_selector_is_a_usage_error(capsys: Any) -> None:
    code, _, err = run(["undo"], capsys)
    assert code == 2
    assert "provide a RUN_ID or use --last" in err


def test_undo_unknown_run_is_a_usage_error(capsys: Any) -> None:
    code, _, err = run(["undo", "does-not-exist"], capsys)
    assert code == 2
    assert "unknown run" in err


def test_undo_last_without_history(capsys: Any) -> None:
    code, out, _ = run(["undo", "--last"], capsys)
    assert code == 0
    assert "No runs available to undo" in out


def test_history_is_empty_on_a_fresh_install(capsys: Any) -> None:
    code, out, _ = run(["history"], capsys)
    assert code == 0
    assert "No runs recorded yet" in out


def test_history_after_a_run(downloads: Path, write_file: Any, capsys: Any) -> None:
    write_file(downloads / "photo.jpg")
    run(["organize", str(downloads), "--apply"], capsys)

    code, out, _ = run(["history"], capsys)
    assert code == 0
    assert "Images" not in out
    assert "active" in out

    code, out, _ = run(["history", "--json"], capsys)
    payload = json.loads(out)
    assert code == 0
    assert payload["runs"][0]["moves"] == 1


def test_history_limit_must_be_positive(capsys: Any) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["history", "--limit", "0"])
    assert exit_info.value.code == 2


def test_rules_can_read_a_config_file(downloads: Path, write_file: Any, capsys: Any) -> None:
    config = write_file(downloads / "custom.toml", '[categories]\nDesign = [".fig"]\n')

    code, out, _ = run(["rules", "-c", str(config), "--json"], capsys)

    payload = json.loads(out)
    assert code == 0
    assert payload["config"] == str(config)
    assert "Design" in {item["name"] for item in payload["categories"]}
