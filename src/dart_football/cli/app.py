from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Literal

import questionary
from questionary import Choice, Separator
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dart_football.cli.game_header import render_game_header
from dart_football.cli.play_ui import prompt_play_event
from dart_football.display import team_display_name
from dart_football.engine.events import CallTimeout, Event
from dart_football.engine.phases import Phase
from dart_football.engine.session import GameSession
from dart_football.engine.state import GameState, TeamId
from dart_football.engine.transitions import TransitionError
from dart_football.rules.loader import default_ruleset_path, load_rules_path

_SAVE_STYLE = questionary.Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:green"),
    ]
)

_TIMEOUT_PAUSE_STYLE = questionary.Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:green"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
    ]
)


def _halftime_pause(console: Console) -> None:
    console.print()
    console.print(
        Panel(
            "[bold]Halftime.[/bold]\n\n"
            "The first half is over. When you're ready, continue to the second half (3rd quarter).",
            title="Halftime",
            border_style="magenta",
        )
    )
    questionary.select(
        "Continue?",
        choices=[
            Choice("Continue", "continue"),
        ],
        style=_TIMEOUT_PAUSE_STYLE,
    ).ask()


def _apply(session: GameSession, event: Event, console: Console) -> None:
    state_before, _ = session.current_state_phase()
    q_before = state_before.clock.quarter
    out = session.apply(event)
    if isinstance(out, TransitionError):
        console.print(f"[red]error:[/red] {out.message}")
    else:
        console.print(f"[green]{out.effects_summary}[/green]")
        state_after, _ = session.current_state_phase()
        if q_before == 2 and state_after.clock.quarter == 3:
            _halftime_pause(console)


def _undo(session: GameSession, console: Console) -> None:
    if session.undo():
        console.print("[yellow]Undid last play.[/yellow]")
    else:
        console.print("[dim]Nothing to undo.[/dim]")


def _save_prompt(session: GameSession, console: Console) -> None:
    console.print(
        Panel(
            "Save the current session to a JSON file.",
            title="Save",
            border_style="blue",
        )
    )
    path = questionary.text(
        "Path:",
        style=_SAVE_STYLE,
    ).ask()
    if path is None or not str(path).strip():
        return
    p = Path(str(path).strip())
    try:
        session.save(p)
        console.print(f"[green]Saved[/green] {p.resolve()}")
    except OSError as e:
        console.print(f"[red]Save failed:[/red] {e}")


def _pick_timeout_team(console: Console) -> TeamId | None:
    console.print()
    console.print(
        Panel(
            "Choose which team's timeout to charge. "
            "Use [bold]Cancel[/bold] if you opened this by mistake (no timeout charged).\n\n"
            "After a timeout, you can [bold]Undo[/bold] on the next screen to pick a different team.",
            title="Timeout — which team?",
            border_style="cyan",
        )
    )
    pick = questionary.select(
        "Which team is calling timeout?",
        choices=[
            Choice(team_display_name(TeamId.RED), "red"),
            Choice(team_display_name(TeamId.GREEN), "green"),
            Separator("─" * 48),
            Choice("Cancel (no timeout charged)", "cancel"),
        ],
        style=_TIMEOUT_PAUSE_STYLE,
    ).ask()
    if pick is None or pick == "cancel":
        return None
    return TeamId.RED if pick == "red" else TeamId.GREEN


def _pause_after_timeout(console: Console) -> Literal["continue", "undo_pick"]:
    console.print()
    console.print(
        Panel(
            "[bold]Gameplay is paused.[/bold]\n\n"
            "A timeout has been charged. When ready, choose [bold]Continue[/bold] to return to the game.\n\n"
            "If you chose the wrong team, pick [bold]Undo[/bold] to remove this timeout and select Red or Green again.",
            title="Timeout",
            border_style="yellow",
        )
    )
    choice = questionary.select(
        "Ready to continue?",
        choices=[
            Choice("Continue", "continue"),
            Separator("─" * 48),
            Choice("Undo — wrong team, re-pick who calls timeout", "undo_pick"),
        ],
        style=_TIMEOUT_PAUSE_STYLE,
    ).ask()
    if choice == "undo_pick":
        return "undo_pick"
    return "continue"


def _run_timeout_flow(session: GameSession, console: Console) -> None:
    while True:
        team = _pick_timeout_team(console)
        if team is None:
            return
        out = session.apply(CallTimeout(team))
        if isinstance(out, TransitionError):
            console.print(f"[red]error:[/red] {out.message}")
            return
        console.print(f"[green]{out.effects_summary}[/green]")
        action = _pause_after_timeout(console)
        if action == "undo_pick":
            if session.undo():
                console.print("[yellow]Timeout undone — choose the team again.[/yellow]")
                continue
            console.print("[red]Could not undo the timeout.[/red]")
            return
        return


def _show_history(session: GameSession, console: Console) -> None:
    if not session.records:
        console.print("[dim]No plays recorded yet.[/dim]")
        return
    t = Table(title="Full play history", show_lines=True)
    t.add_column("#", style="dim", justify="right")
    t.add_column("From → To", style="cyan")
    t.add_column("Summary", style="white")
    for r in session.records:
        t.add_row(
            str(r.seq),
            f"{r.phase_before.value} → {r.phase_after.value}",
            r.effects_summary,
        )
    console.print(t)


def run_interactive(session: GameSession) -> None:
    console = Console()
    for w in session.load_warnings:
        console.print(f"[bold yellow]Warning:[/bold yellow] {w}")

    while True:
        state, phase = session.current_state_phase()
        console.print()
        render_game_header(console, session, state, phase)

        pick = prompt_play_event(console, phase, session.rules, state)
        if pick is None:
            continue

        if pick[0] == "meta":
            m = pick[1]
            if m == "quit":
                console.print("Goodbye.")
                break
            if m == "undo":
                _undo(session, console)
            elif m == "save":
                _save_prompt(session, console)
            elif m == "history":
                _show_history(session, console)
            elif m == "timeout":
                _run_timeout_flow(session, console)
            continue

        if pick[0] == "event":
            _apply(session, pick[1], console)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="dart-football")
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
    args = p.parse_args(argv)

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
    run_interactive(session)


if __name__ == "__main__":
    main()
