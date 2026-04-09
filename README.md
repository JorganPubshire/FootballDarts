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

Use `python -m dart_football` — not `python -m dart_football.cli` (the terminal CLI entry is `dart_football.cli.app:main`).

Options: `--rules path\to\rules.toml`, `--load session.json`, `--force` (with `--load` when ruleset metadata does not match).

## Graphical UI

Install GUI dependencies, then start the local browser dashboard:

```text
pip install -e ".[gui]"
python -m dart_football.gui
```

Or use the console script (if `Scripts` is on `PATH`):

```text
dart-football-gui
```

Same session options as the terminal CLI (`--rules`, `--load`, `--force`, `--large-field`).
