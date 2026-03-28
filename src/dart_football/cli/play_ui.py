"""Play-first CLI: pick a play, read rules on screen, then enter dart details."""

from __future__ import annotations

import secrets
from typing import Literal

import questionary
from questionary import Choice, Separator
from rich.console import Console
from rich.panel import Panel

from dart_football.display import dart_help, team_display_name
from dart_football.engine.events import (
    ChooseKickOrReceive,
    ChoosePatOrTwo,
    CoinTossWinner,
    Event,
    ExtraPointOutcome,
    FieldGoalOutcome,
    FourthDownChoice,
    KickoffKick,
    PuntKick,
    ScrimmageDefense,
    ScrimmageOffense,
    TwoPointOutcome,
)
from dart_football.engine.phases import Phase
from dart_football.engine.state import GameState, TeamId
from dart_football.rules.schema import RuleSet

_Q_STYLE = questionary.Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:green"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
    ]
)

_MetaAction = Literal["undo", "save", "history", "quit", "timeout_red", "timeout_green"]
ActionPick = tuple[Literal["event"], Event] | tuple[Literal["meta"], _MetaAction]


def _fg_in_range(state: GameState, rules: RuleSet) -> bool:
    dist = abs(state.field.goal_yard - state.field.scrimmage_line)
    return dist <= rules.field_goal.max_distance_yards


def _read_int(console: Console, prompt: str, lo: int, hi: int) -> int | None:
    while True:
        raw = questionary.text(prompt, style=_Q_STYLE).ask()
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


def _prompt_hit_kind(console: Console, intro: str) -> Literal["wedge", "green", "red"] | None:
    console.print(Panel(intro, border_style="dim", title="Dart landing"))
    c = questionary.select(
        "Where did the dart land?",
        choices=[
            Choice("Numbered wedge (1–20)", "wedge"),
            Choice("Green bull", "green"),
            Choice("Red bull", "red"),
        ],
        style=_Q_STYLE,
    ).ask()
    return c  # type: ignore[return-value]


def _collect_offense_rings(console: Console) -> tuple[bool, bool, bool | None] | None:
    r = questionary.select(
        "Which ring on that wedge?",
        choices=[
            Choice("Single (inner single)", "single"),
            Choice("Double ring", "double"),
            Choice("Triple (treble) ring", "triple"),
        ],
        style=_Q_STYLE,
    ).ask()
    if r is None:
        return None
    if r == "single":
        return False, False, None
    if r == "double":
        return True, False, None
    io = questionary.select(
        "Inner or outer treble?",
        choices=[
            Choice("Inner treble (smaller ring)", True),
            Choice("Outer treble (larger ring)", False),
        ],
        style=_Q_STYLE,
    ).ask()
    if io is None:
        return None
    return False, True, io


def _collect_defense_rings(console: Console) -> tuple[bool, bool, bool | None] | None:
    return _collect_offense_rings(console)


def _flow_kickoff(console: Console, rules: RuleSet, state: GameState) -> KickoffKick | None:
    console.print(
        Panel(
            dart_help.kickoff_instructions(rules, state),
            title="Kickoff — read the board",
            border_style="cyan",
        )
    )
    hk = _prompt_hit_kind(console, "Kickoff dart — record where it landed.")
    if hk is None:
        return None
    if hk == "green":
        return KickoffKick(segment=rules.scrimmage.bull_green_segment, bull="green")
    if hk == "red":
        return KickoffKick(segment=rules.scrimmage.bull_red_segment, bull="red")
    lo, hi = rules.kickoff.segment_min, rules.kickoff.segment_max
    seg = _read_int(console, f"Wedge number ({lo}–{hi}): ", lo, hi)
    if seg is None:
        return None
    return KickoffKick(segment=seg, bull="none")


def _flow_scrimmage_offense(console: Console, rules: RuleSet, state: GameState) -> ScrimmageOffense | None:
    console.print(
        Panel(
            dart_help.scrimmage_offense_instructions(rules, state),
            title="Offense — read the board",
            border_style="cyan",
        )
    )
    hk = _prompt_hit_kind(console, "Offense dart — record where it landed.")
    if hk is None:
        return None
    sc = rules.scrimmage
    if hk == "green":
        return ScrimmageOffense(
            segment=sc.bull_green_segment,
            bull="green",
        )
    if hk == "red":
        return ScrimmageOffense(
            segment=sc.bull_red_segment,
            bull="red",
        )
    seg = _read_int(console, f"Wedge number ({sc.segment_min}–{sc.segment_max}): ", sc.segment_min, sc.segment_max)
    if seg is None:
        return None
    rings = _collect_offense_rings(console)
    if rings is None:
        return None
    dr, tr, t_in = rings
    return ScrimmageOffense(
        segment=seg,
        double_ring=dr,
        triple_ring=tr,
        triple_inner=t_in,
        bull="none",
    )


def _flow_scrimmage_defense(console: Console, rules: RuleSet, state: GameState) -> ScrimmageDefense | None:
    console.print(
        Panel(
            dart_help.scrimmage_defense_instructions(rules, state),
            title="Defense — read the board",
            border_style="cyan",
        )
    )
    hk = _prompt_hit_kind(console, "Defense dart — record where it landed.")
    if hk is None:
        return None
    sc = rules.scrimmage
    if hk == "green":
        return ScrimmageDefense(
            segment=sc.bull_green_segment,
            bull="green",
        )
    if hk == "red":
        return ScrimmageDefense(
            segment=sc.bull_red_segment,
            bull="red",
        )
    seg = _read_int(console, f"Wedge number ({sc.segment_min}–{sc.segment_max}): ", sc.segment_min, sc.segment_max)
    if seg is None:
        return None
    rings = _collect_defense_rings(console)
    if rings is None:
        return None
    dr, tr, t_in = rings
    return ScrimmageDefense(
        segment=seg,
        bull="none",
        double_ring=dr,
        triple_ring=tr,
        triple_inner=t_in,
    )


def _flow_punt(console: Console, rules: RuleSet, state: GameState) -> PuntKick | None:
    console.print(
        Panel(
            dart_help.punt_instructions(rules, state),
            title="Punt — read the board",
            border_style="cyan",
        )
    )
    hk = _prompt_hit_kind(console, "Punt dart — record where it landed.")
    if hk is None:
        return None
    if hk == "green":
        return PuntKick(segment=rules.scrimmage.bull_green_segment, bull="green")
    if hk == "red":
        return PuntKick(segment=rules.scrimmage.bull_red_segment, bull="red")
    pr = rules.punt
    seg = _read_int(console, f"Wedge number ({pr.segment_min}–{pr.segment_max}): ", pr.segment_min, pr.segment_max)
    if seg is None:
        return None
    return PuntKick(segment=seg, bull="none")


def _meta_block(phase: Phase) -> list[Choice[str]]:
    choices = [
        Choice("Undo last play", "meta_undo"),
        Choice("Save session…", "meta_save"),
        Choice("Show full play history", "meta_history"),
    ]
    if phase not in (Phase.PRE_GAME_COIN_TOSS, Phase.GAME_OVER):
        choices.append(Choice("Timeout — Red (no play counted)", "meta_timeout_red"))
        choices.append(Choice("Timeout — Green (no play counted)", "meta_timeout_green"))
    choices.append(Choice("Exit", "meta_quit"))
    return choices


def _flow_coin_toss(console: Console) -> CoinTossWinner | None:
    """Green calls heads/tails; random 0/1 → heads/tails; correct call wins the toss."""
    call = questionary.select(
        "Green — call it in the air:",
        choices=[
            Choice("Heads", "heads"),
            Choice("Tails", "tails"),
        ],
        style=_Q_STYLE,
    ).ask()
    if call is None:
        return None
    # 0 = heads, 1 = tails
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


def prompt_play_event(
    console: Console,
    phase: Phase,
    rules: RuleSet,
    state: GameState,
) -> ActionPick | None:
    """Top-level 'Select a play' menu, then phase-specific dart/outcome collection."""
    meta = _meta_block(phase)

    if phase is Phase.PRE_GAME_COIN_TOSS:
        choices: list = [
            Choice("Flip coin (Green calls heads or tails)", "coin_flip"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Select a play", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "coin_flip":
            ev = _flow_coin_toss(console)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.CHOOSE_KICK_OR_RECEIVE:
        w = state.coin_toss_winner
        if w is not None:
            console.print(
                f"[bold]{team_display_name(w)} won the toss[/bold] — choose kick or receive."
            )
        choices = [
            Choice("Winner kicks off (opponent receives)", "kr_kick"),
            Choice("Winner receives (opponent kicks)", "kr_recv"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Select a play", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        if str(pick).startswith("meta_"):
            return _dispatch_meta(str(pick))
        if pick == "kr_kick":
            return ("event", ChooseKickOrReceive(kick=True))
        if pick == "kr_recv":
            return ("event", ChooseKickOrReceive(kick=False))
        return None

    if phase is Phase.KICKOFF_KICK:
        choices = [
            Choice("Continue — dart prompts below", "go"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Kickoff", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "go":
            ev = _flow_kickoff(console, rules, state)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.SCRIMMAGE_OFFENSE:
        choices = [
            Choice("Offense play (scrimmage dart)", "off_scrim"),
        ]
        if state.downs.down >= 2:
            choices.append(Choice("Punt", "fd_punt"))
        fg_pdf = state.downs.down in (3, 4) or state.last_play_of_period
        if fg_pdf and _fg_in_range(state, rules):
            choices.append(Choice("Field goal", "fd_fg"))
        choices.append(Separator("─" * 48))
        choices.extend(meta)
        pick = questionary.select("Select a play", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "fd_punt":
            return ("event", FourthDownChoice(kind="punt"))
        if pick == "fd_fg":
            return ("event", FourthDownChoice(kind="field_goal"))
        if pick == "off_scrim":
            ev = _flow_scrimmage_offense(console, rules, state)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.SCRIMMAGE_DEFENSE:
        choices = [
            Choice("Continue — dart prompts below", "go"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Defense", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "go":
            ev = _flow_scrimmage_defense(console, rules, state)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.FOURTH_DOWN_DECISION:
        choices = [
            Choice("Go for it", "fd_go"),
            Choice("Punt", "fd_punt"),
            Choice("Field goal", "fd_fg"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Select a play", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "fd_go":
            return ("event", FourthDownChoice(kind="go"))
        if pick == "fd_punt":
            return ("event", FourthDownChoice(kind="punt"))
        if pick == "fd_fg":
            return ("event", FourthDownChoice(kind="field_goal"))
        return None

    if phase is Phase.FIELD_GOAL_ATTEMPT:
        console.print(
            Panel(
                dart_help.field_goal_instructions(state, rules),
                title="Field goal",
                border_style="cyan",
            )
        )
        choices = [
            Choice("Field goal — good", "fg_good"),
            Choice("Field goal — missed", "fg_miss"),
            Choice("Field goal — blocked", "fg_block"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Select a play", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "fg_good":
            return ("event", FieldGoalOutcome(kind="good"))
        if pick == "fg_miss":
            return ("event", FieldGoalOutcome(kind="miss"))
        if pick == "fg_block":
            return ("event", FieldGoalOutcome(kind="blocked"))
        return None

    if phase is Phase.PUNT_ATTEMPT:
        choices = [
            Choice("Continue — dart prompts below", "go"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Punt", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "go":
            ev = _flow_punt(console, rules, state)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.PAT_OR_TWO_DECISION:
        choices = [
            Choice("Try for 1 (extra point)", "pat_1"),
            Choice("Try for 2 (two-point conversion)", "pat_2"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Select a play", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "pat_1":
            return ("event", ChoosePatOrTwo(extra_point=True))
        if pick == "pat_2":
            return ("event", ChoosePatOrTwo(extra_point=False))
        return None

    if phase is Phase.EXTRA_POINT_ATTEMPT:
        console.print(Panel(dart_help.pat_instructions(rules, state), title="Extra point", border_style="cyan"))
        choices = [
            Choice("PAT — good", "xpa_good"),
            Choice("PAT — no good", "xpa_bad"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Select a play", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "xpa_good":
            return ("event", ExtraPointOutcome(good=True))
        if pick == "xpa_bad":
            return ("event", ExtraPointOutcome(good=False))
        return None

    if phase is Phase.TWO_POINT_ATTEMPT:
        console.print(Panel(dart_help.two_point_instructions(rules, state), title="Two-point try", border_style="cyan"))
        choices = [
            Choice("Two-point — good", "tpc_good"),
            Choice("Two-point — no good", "tpc_bad"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Select a play", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "tpc_good":
            return ("event", TwoPointOutcome(good=True))
        if pick == "tpc_bad":
            return ("event", TwoPointOutcome(good=False))
        return None

    if phase is Phase.GAME_OVER:
        choices = list(meta)
        pick = questionary.select("Select an action", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        return _dispatch_meta(str(pick))

    console.print(f"[yellow]Phase {phase.value} has no play menu yet.[/yellow]")
    choices = list(meta)
    pick = questionary.select("Select an action", choices=choices, style=_Q_STYLE).ask()
    if pick is None:
        return None
    return _dispatch_meta(str(pick))


def _dispatch_meta(tag: str) -> ActionPick | None:
    if tag == "meta_undo":
        return ("meta", "undo")
    if tag == "meta_save":
        return ("meta", "save")
    if tag == "meta_history":
        return ("meta", "history")
    if tag == "meta_quit":
        return ("meta", "quit")
    if tag == "meta_timeout_red":
        return ("meta", "timeout_red")
    if tag == "meta_timeout_green":
        return ("meta", "timeout_green")
    return None
