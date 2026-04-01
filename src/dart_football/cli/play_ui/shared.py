"""Shared questionary styles, meta-menu helpers, and small input utilities."""

from __future__ import annotations

import secrets
from typing import Literal

import questionary
from questionary import Choice
from rich.console import Console
from rich.panel import Panel

from dart_football.display import dart_help, team_display_name
from dart_football.engine.events import CoinTossWinner
from dart_football.engine.phases import Phase
from dart_football.engine.state import GameState, TeamId
from dart_football.rules.schema import RuleSet

QUESTIONARY_STYLE = questionary.Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:green"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
    ]
)

MetaAction = Literal["undo", "save", "history", "quit", "timeout"]


def field_goal_in_range(state: GameState, rules: RuleSet) -> bool:
    dist = abs(state.field.goal_yard - state.field.scrimmage_line)
    return dist <= rules.field_goal.max_distance_yards


def read_int(console: Console, prompt: str, lo: int, hi: int) -> int | None:
    while True:
        raw = questionary.text(prompt, style=QUESTIONARY_STYLE).ask()
        if raw is None:
            return None
        s = raw.strip()
        if not s.isdigit():
            console.print(f"[red]Enter a whole number from {lo} to {hi}.[/red]")
            continue
        v = int(s)
        if lo <= v <= hi:
            return v
        console.print(f"[red]Must be between {lo} and {hi}.[/red]")


def prompt_hit_kind(console: Console) -> Literal["wedge", "green", "red"] | None:
    c = questionary.select(
        "Where did the dart land?",
        choices=[
            Choice("Numbered wedge", "wedge"),
            Choice("Green bull", "green"),
            Choice("Red bull", "red"),
        ],
        style=QUESTIONARY_STYLE,
    ).ask()
    return c  # type: ignore[return-value]


def collect_offense_rings(console: Console) -> tuple[bool, bool, bool | None] | None:
    r = questionary.select(
        "Which ring on that wedge?",
        choices=[
            Choice("Single", "single"),
            Choice("Double", "double"),
            Choice("Triple", "triple"),
        ],
        style=QUESTIONARY_STYLE,
    ).ask()
    if r is None:
        return None
    if r == "single":
        return False, False, None
    if r == "double":
        return True, False, None
    io = questionary.select(
        "Inner or outer triple?",
        choices=[
            Choice("Inner triple", True),
            Choice("Outer triple", False),
        ],
        style=QUESTIONARY_STYLE,
    ).ask()
    if io is None:
        return None
    return False, True, io


def meta_choices_for_phase(phase: Phase) -> list[Choice[str]]:
    choices: list[Choice[str]] = []
    if phase not in (Phase.PRE_GAME_COIN_TOSS, Phase.GAME_OVER):
        choices.append(Choice("Timeout", "meta_timeout"))
    if phase is not Phase.PRE_GAME_COIN_TOSS:
        choices.extend(
            [
                Choice("Undo", "meta_undo"),
                Choice("Save", "meta_save"),
                Choice("History", "meta_history"),
            ]
        )
    choices.append(Choice("Exit", "meta_quit"))
    return choices


def prompt_coin_toss_virtual(console: Console) -> CoinTossWinner | None:
    """Green calls heads/tails; random 0/1 → heads/tails; correct call wins the toss."""
    console.print(
        Panel(
            "[bold]Virtual coin toss[/bold] (not using the dartboard)\n\n"
            "Green calls [bold]heads[/bold] or [bold]tails[/bold] before the flip. "
            "If the call matches the coin, Green wins the toss; otherwise Red wins.",
            title="Virtual coin toss",
            border_style="cyan",
        )
    )
    call = questionary.select(
        "What does Green call before the flip?",
        choices=[
            Choice("Heads", "heads"),
            Choice("Tails", "tails"),
        ],
        style=QUESTIONARY_STYLE,
    ).ask()
    if call is None:
        return None
    flip = secrets.randbelow(2)
    flip_is_heads = flip == 0
    flip_word = "heads" if flip_is_heads else "tails"
    call_is_heads = call == "heads"
    green_wins = call_is_heads == flip_is_heads
    winner = TeamId.GREEN if green_wins else TeamId.RED
    console.print(
        f"[bold]Flip: {flip_word}[/bold]. Green called {call} — "
        f"[yellow]{team_display_name(winner)} wins the toss.[/yellow]"
    )
    return CoinTossWinner(winner)


def prompt_coin_toss_darts(console: Console, rules: RuleSet) -> CoinTossWinner | None:
    """Oldest then youngest; closest to center wins — user records the result."""
    console.print(
        Panel(
            dart_help.coin_toss_dart_instructions(rules),
            title="Coin toss — darts",
            border_style="cyan",
        )
    )
    closest = questionary.select(
        "Who was closer to the center of the board?",
        choices=[
            Choice(f"{team_display_name(TeamId.RED)}", TeamId.RED),
            Choice(f"{team_display_name(TeamId.GREEN)}", TeamId.GREEN),
        ],
        style=QUESTIONARY_STYLE,
    ).ask()
    if closest is None:
        return None
    console.print(
        f"[yellow]{team_display_name(closest)} wins the toss[/yellow] — choose kick or receive next."
    )
    return CoinTossWinner(closest)


def prompt_coin_toss_menu(console: Console, rules: RuleSet) -> CoinTossWinner | None:
    console.print(
        Panel(
            "[bold]Coin toss[/bold]\n\n"
            "Pick how you want to decide who kicks off and who receives.\n"
            "Default is a [bold]dart toss[/bold] at the board; you can use a fair [bold]virtual[/bold] heads/tails flip instead.",
            title="How to toss",
            border_style="cyan",
        )
    )
    mode = questionary.select(
        "How should the coin toss be decided?",
        choices=[
            Choice("Virtual flip (heads/tails in the app)", "virtual"),
            Choice("Darts on the board", "darts"),
        ],
        style=QUESTIONARY_STYLE,
    ).ask()
    if mode is None:
        return None
    if mode == "virtual":
        return prompt_coin_toss_virtual(console)
    return prompt_coin_toss_darts(console, rules)
