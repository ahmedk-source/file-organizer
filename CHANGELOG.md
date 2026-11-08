# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-08

### Added

- `organize` command that previews by default and only moves files with
  `--apply`.
- Extension-based categories for images, PDFs, documents, programs, archives,
  audio, video, fonts, code and a fallback category.
- Conflict strategies: `rename` (default), `skip` and `overwrite`, with
  content-aware duplicate detection in `rename` mode.
- Append-only JSON Lines journal, `history` command and fully reversible
  `undo` command that replays moves in reverse and prunes empty folders.
- TOML configuration with strict validation, custom categories, compound
  extensions and per-category overrides.
- Recursive mode, hidden-file and partial-download protection, symlink
  handling, and collision-safe names within a single run.
- Machine-readable `--json` output for `organize`, `undo`, `history` and
  `rules`, with a versioned payload schema.
- Test-suite (148 tests), strict `mypy` configuration, `ruff` linting, and a
  GitHub Actions matrix across Linux, macOS and Windows.

### Security

- Partial browser downloads (`.crdownload`, `.part`, `.tmp`, ...) are never
  moved while they are still being written.
- The destination folder is excluded from recursive scans, and the journal is
  stored outside the organised folder.
- Category names are validated against Windows reserved names and forbidden
  characters before any folder is created.
