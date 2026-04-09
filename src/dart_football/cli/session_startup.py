"""Shared CLI argv parsing and ``GameSession`` construction for interactive and GUI modes."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from dart_football.engine.phases import Phase
from dart_football.engine.session import GameSession
from dart_football.engine.state import GameState
from dart_football.rules.loader import default_ruleset_path, load_rules_path
from dart_football.rules.schema import RuleSet


def _add_session_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--rules",
        type=str,
        default=None,
        help="Path to rules TOML (default: rules/standard.toml in the project)",
    )
    p.add_argument("--load", type=str, default=None, help="Load session JSON")
    p.add_argument(
        "--force",
        action="store_true",
        help="Load session even if ruleset id/version does not match the rules file (risky)",
    )
    p.add_argument(
        "--large-field",
        action="store_true",
        help="Draw the multi-row proportional field with border (default: single-line field)",
    )


def make_cli_arg_parser() -> argparse.ArgumentParser:
    """Argument parser for the terminal CLI (``dart-football`` / ``python -m dart_football``)."""
    p = argparse.ArgumentParser(prog="dart-football")
    _add_session_arguments(p)
    return p


def make_gui_arg_parser() -> argparse.ArgumentParser:
    """Argument parser for the graphical dashboard (``dart-football-gui`` / ``python -m dart_football.gui``)."""
    p = argparse.ArgumentParser(
        prog="dart-football-gui",
        description="Dart Football graphical dashboard (local browser UI).",
    )
    _add_session_arguments(p)
    return p


def make_arg_parser() -> argparse.ArgumentParser:
    """Same as :func:`make_cli_arg_parser` (backward-compatible name)."""
    return make_cli_arg_parser()


def session_from_cli_args(args: argparse.Namespace) -> tuple[GameSession, Path, RuleSet]:
    """
    Build a session from parsed CLI args. Calls ``sys.exit`` on failure (missing rules file, bad load).
    """
    rules_path = Path(args.rules) if args.rules else default_ruleset_path()
    if not rules_path.is_file():
        print(f"rules file not found: {rules_path}", file=sys.stderr)
        sys.exit(1)
    rules = load_rules_path(rules_path)
    initial = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    session: GameSession
    if args.load:
        try:
            session = GameSession.load(
                args.load,
                lambda pth: load_rules_path(Path(pth)),
                force=args.force,
            )
        except ValueError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        if args.large_field:
            session = replace(session, large_field=True)
    else:
        session = GameSession.new(
            initial,
            Phase.PRE_GAME_COIN_TOSS,
            rules,
            rules_path=str(rules_path.resolve()),
            large_field=args.large_field,
        )
    return session, rules_path, rules


def build_game_session(argv: list[str] | None) -> tuple[GameSession, Path, RuleSet]:
    """Parse argv and build session. For tests and direct callers."""
    p = make_cli_arg_parser()
    args = p.parse_args(argv)
    return session_from_cli_args(args)
