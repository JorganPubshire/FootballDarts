# Dart Football

Python CLI and rules-driven game engine.

## Run

From the project directory, after installing the package in editable mode:

```text
pip install -e ".[dev]"
```

Then either:

```text
python -m dart_football
```

or (if your Python `Scripts` folder is on `PATH`):

```text
dart-football
```

Use `python -m dart_football` — not `python -m dart_football.cli` (the CLI lives under `dart_football.cli.app`).

Options: `--rules path\to\rules.toml`, `--load session.json`, `--force` (with `--load` when ruleset metadata does not match).
