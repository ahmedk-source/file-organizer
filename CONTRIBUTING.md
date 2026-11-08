# Contributing

Thanks for taking the time to improve `file-organizer`.

## Development setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -e ".[dev]"
pre-commit install   # optional, runs ruff and mypy on commit
```

## Before opening a pull request

Run the same checks as CI:

```bash
ruff check .
ruff format --check .
mypy
pytest --cov
```

All four must pass. New behaviour needs a test; bug fixes should include a
regression test that fails without the fix.

## Guidelines

- Keep the runtime dependency list empty. The standard library is a feature.
- Preserve the plan/execute split: `plan()` must never write to the filesystem.
- Treat destructive behaviour as opt-in and document it in the README.
- Use ASCII output in the CLI; Windows terminals with legacy code pages are
  still common.
- Update `CHANGELOG.md` for user-visible changes.

## Reporting bugs

Please include:

- the command you ran (with `--json` output if possible),
- the operating system and Python version,
- the relevant part of the journal (`file-organizer history`),
- what you expected and what happened instead.

Never paste the contents of personal files; file names and the journal are
usually enough to reproduce a sorting problem.
