"""Play-first CLI: pick a play, read rules on screen, then enter dart details."""

from __future__ import annotations

import secrets
from typing import Literal, cast

import questionary
from questionary import Choice, Separator
from rich.console import Console
from rich.panel import Panel

from dart_football.display import dart_help, team_display_name
from dart_football.engine.events import (
    ConfirmSafetyKickoff,
    ChooseFieldGoalAfterGreen,
    ChooseKickoffKind,
    ChooseKickoffTouchbackOrRun,
    ChooseKickOrReceive,
    ChooseExtraPointOrTwo,
    CoinTossWinner,
    Event,
    ExtraPointOutcome,
    FieldGoalDefenseDart,
    FieldGoalFakeOffenseDart,
    FieldGoalOffenseDart,
    FourthDownChoice,
    KickoffKick,
    KickoffReturnKick,
    KickoffRunOutKick,
    PuntKick,
    ScrimmageDefense,
    ScrimmageOffense,
    ScrimmageStripDart,
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

_MetaAction = Literal["undo", "save", "history", "quit", "timeout"]
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


def _prompt_hit_kind(console: Console) -> Literal["wedge", "green", "red"] | None:
    c = questionary.select(
        "Where did the dart land?",
        choices=[
            Choice("Numbered wedge", "wedge"),
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
            Choice("Single", "single"),
            Choice("Double", "double"),
            Choice("Triple", "triple"),
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
        "Inner or outer triple?",
        choices=[
            Choice("Inner triple", True),
            Choice("Outer triple", False),
        ],
        style=_Q_STYLE,
    ).ask()
    if io is None:
        return None
    return False, True, io


def _flow_kickoff_dart(
    console: Console,
    rules: RuleSet,
    state: GameState,
    *,
    panel_title: str,
    instructions: str,
) -> KickoffKick | None:
    console.print(Panel(instructions, title=panel_title, border_style="cyan"))
    hk = _prompt_hit_kind(console)
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


def _flow_kickoff(console: Console, rules: RuleSet, state: GameState) -> KickoffKick | None:
    return _flow_kickoff_dart(
        console,
        rules,
        state,
        panel_title="Kickoff — read the board",
        instructions=dart_help.kickoff_instructions(rules, state),
    )


def _flow_onside_kick(console: Console, rules: RuleSet, state: GameState) -> KickoffKick | None:
    return _flow_kickoff_dart(
        console,
        rules,
        state,
        panel_title="Onside kick — read the board",
        instructions=dart_help.onside_kick_instructions(rules, state),
    )


def _flow_kickoff_run_out(console: Console, rules: RuleSet, state: GameState) -> KickoffRunOutKick | None:
    console.print(
        Panel(
            dart_help.kickoff_run_out_instructions(rules, state),
            title="Run out — read the board",
            border_style="cyan",
        )
    )
    hk = _prompt_hit_kind(console)
    if hk is None:
        return None
    if hk == "green":
        return KickoffRunOutKick(segment=rules.scrimmage.bull_green_segment, bull="green")
    if hk == "red":
        return KickoffRunOutKick(segment=rules.scrimmage.bull_red_segment, bull="red")
    lo, hi = rules.kickoff.segment_min, rules.kickoff.segment_max
    seg = _read_int(console, f"Wedge number ({lo}–{hi}): ", lo, hi)
    if seg is None:
        return None
    return KickoffRunOutKick(segment=seg, bull="none")


def _flow_kickoff_return(console: Console, rules: RuleSet, state: GameState) -> KickoffReturnKick | None:
    console.print(
        Panel(
            dart_help.kickoff_return_instructions(rules, state),
            title="Kickoff return — read the board",
            border_style="cyan",
        )
    )
    hk = _prompt_hit_kind(console)
    if hk is None:
        return None
    sc = rules.scrimmage
    if hk == "green":
        return KickoffReturnKick(segment=sc.bull_green_segment, bull="green")
    if hk == "red":
        return KickoffReturnKick(segment=sc.bull_red_segment, bull="red")
    seg = _read_int(console, f"Wedge number ({sc.segment_min}–{sc.segment_max}): ", sc.segment_min, sc.segment_max)
    if seg is None:
        return None
    # Wedges 13–20: double/triple affect return yards; 1–12 uses fixed +12 (rings ignored in engine).
    if 13 <= seg <= 20:
        rings = _collect_offense_rings(console)
        if rings is None:
            return None
        dr, tr, t_in = rings
    else:
        dr, tr, t_in = False, False, None
    return KickoffReturnKick(
        segment=seg,
        double_ring=dr,
        triple_ring=tr,
        triple_inner=t_in,
        bull="none",
    )


def _flow_scrimmage_offense(console: Console, rules: RuleSet, state: GameState) -> ScrimmageOffense | None:
    console.print(
        Panel(
            dart_help.scrimmage_offense_instructions(rules, state),
            title="Offense — read the board",
            border_style="cyan",
        )
    )
    hk = _prompt_hit_kind(console)
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


def _print_defense_instructions_panel(console: Console, rules: RuleSet, state: GameState) -> None:
    console.print(
        Panel(
            dart_help.scrimmage_defense_instructions(rules, state),
            title="Defense — read the board",
            border_style="cyan",
        )
    )


def _finish_scrimmage_defense_after_hit_kind(
    console: Console,
    rules: RuleSet,
    state: GameState,
    hk: Literal["wedge", "green", "red"],
) -> ScrimmageDefense | None:
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
    # Defense yardage never uses double/triple; session may still log defaults.
    return ScrimmageDefense(segment=seg, bull="none", double_ring=False, triple_ring=False, triple_inner=None)


def _flow_field_goal_offense_dart(console: Console, rules: RuleSet, state: GameState) -> FieldGoalOffenseDart | None:
    console.print(
        Panel(
            dart_help.field_goal_offense_dart_instructions(state, rules),
            title="Field goal — kicker",
            border_style="cyan",
        )
    )
    hk = _prompt_hit_kind(console)
    if hk is None:
        return None
    sc = rules.scrimmage
    if hk == "green":
        return FieldGoalOffenseDart(zone="green", segment=sc.bull_green_segment)
    if hk == "red":
        return FieldGoalOffenseDart(zone="red", segment=sc.bull_red_segment)
    seg = _read_int(console, f"Wedge number ({sc.segment_min}–{sc.segment_max}): ", sc.segment_min, sc.segment_max)
    if seg is None:
        return None
    loc = questionary.select(
        "Where did it land for field goal rules?",
        choices=[
            Choice(
                "Inside the triple ring — single/double between double and triple (not on triple scoring)",
                "inner",
            ),
            Choice("On the triple scoring ring (inner or outer triple bed)", "triple"),
            Choice("Outside the triple ring — outer wedge toward the double ring", "outside"),
        ],
        style=_Q_STYLE,
    ).ask()
    if loc is None:
        return None
    z: Literal["inner_triple", "outside_triples", "triple_ring"]
    if loc == "inner":
        z = "inner_triple"
    elif loc == "triple":
        z = "triple_ring"
    else:
        z = "outside_triples"
    return FieldGoalOffenseDart(zone=z, segment=seg)


def _flow_field_goal_fake_offense(console: Console, rules: RuleSet, state: GameState) -> FieldGoalFakeOffenseDart | None:
    console.print(
        Panel(
            dart_help.field_goal_fake_offense_instructions(state, rules),
            title="Fake field goal",
            border_style="cyan",
        )
    )
    hk = _prompt_hit_kind(console)
    if hk is None:
        return None
    sc = rules.scrimmage
    if hk == "green":
        return FieldGoalFakeOffenseDart(segment=sc.bull_green_segment, bull="green")
    if hk == "red":
        return FieldGoalFakeOffenseDart(segment=sc.bull_red_segment, bull="red")
    seg = _read_int(console, f"Wedge number ({sc.segment_min}–{sc.segment_max}): ", sc.segment_min, sc.segment_max)
    if seg is None:
        return None
    rings = _collect_offense_rings(console)
    if rings is None:
        return None
    dr, tr, t_in = rings
    return FieldGoalFakeOffenseDart(
        segment=seg,
        double_ring=dr,
        triple_ring=tr,
        triple_inner=t_in,
        bull="none",
    )


def _finish_field_goal_defense_after_hit_kind(
    console: Console,
    rules: RuleSet,
    state: GameState,
    hk: Literal["wedge", "green", "red"],
) -> FieldGoalDefenseDart | None:
    sc = rules.scrimmage
    if hk == "green":
        return FieldGoalDefenseDart(
            segment=sc.bull_green_segment,
            bull="green",
        )
    if hk == "red":
        return FieldGoalDefenseDart(
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
    return FieldGoalDefenseDart(
        segment=seg,
        bull="none",
        double_ring=dr,
        triple_ring=tr,
        triple_inner=t_in,
    )


def _flow_scrimmage_strip_dart(console: Console, rules: RuleSet, state: GameState) -> ScrimmageStripDart | None:
    console.print(
        Panel(
            dart_help.scrimmage_strip_instructions(rules, state),
            title="Strip dart — numbered wedge only",
            border_style="cyan",
        )
    )
    sc = rules.scrimmage
    seg = _read_int(console, f"Wedge number ({sc.segment_min}–{sc.segment_max}): ", sc.segment_min, sc.segment_max)
    if seg is None:
        return None
    return ScrimmageStripDart(segment=seg)


def _flow_punt(console: Console, rules: RuleSet, state: GameState) -> PuntKick | None:
    console.print(
        Panel(
            dart_help.punt_instructions(rules, state),
            title="Punt — read the board",
            border_style="cyan",
        )
    )
    hk = _prompt_hit_kind(console)
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


def _flow_coin_toss_virtual(console: Console) -> CoinTossWinner | None:
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


def _flow_coin_toss_darts(console: Console, rules: RuleSet) -> CoinTossWinner | None:
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
        style=_Q_STYLE,
    ).ask()
    if closest is None:
        return None
    console.print(
        f"[yellow]{team_display_name(closest)} wins the toss[/yellow] — choose kick or receive next."
    )
    return CoinTossWinner(closest)


def _flow_coin_toss_menu(console: Console, rules: RuleSet) -> CoinTossWinner | None:
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
        style=_Q_STYLE,
    ).ask()
    if mode is None:
        return None
    if mode == "virtual":
        return _flow_coin_toss_virtual(console)
    return _flow_coin_toss_darts(console, rules)


def prompt_play_event(
    console: Console,
    phase: Phase,
    rules: RuleSet,
    state: GameState,
) -> ActionPick | None:
    """Top-level 'Select a play' menu, then phase-specific dart/outcome collection."""
    meta = _meta_block(phase)

    if phase is Phase.PRE_GAME_COIN_TOSS:
        console.print(
            Panel(
                "[bold]Pre-game[/bold]\n\nStart a new game or exit.",
                title="Menu",
                border_style="cyan",
            )
        )
        choices: list = [
            Choice("Start game", "start_game"),
            Choice("Exit", "meta_quit"),
        ]
        pick = questionary.select("What do you want to do?", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "start_game":
            ev = _flow_coin_toss_menu(console, rules)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.CHOOSE_KICK_OR_RECEIVE:
        w = state.coin_toss_winner
        intro = (
            f"[bold]{team_display_name(w)} won the toss[/bold] — winner chooses kick or receive."
            if w is not None
            else "Winner chooses kick or receive."
        )
        console.print(Panel(intro, title="Kick or receive", border_style="cyan"))
        choices = [
            Choice("Kick off", "kr_kick"),
            Choice("Receive", "kr_recv"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Kick off or receive?", choices=choices, style=_Q_STYLE).ask()
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
        if not state.kickoff_type_selected:
            kicker = state.kickoff_kicker
            if kicker is not None:
                console.print(
                    Panel(
                        f"[bold]{team_display_name(kicker)}[/bold] is kicking off.\n\n"
                        "Choose a [bold]regular kickoff[/bold] or an [bold]onside kick[/bold] attempt.",
                        title="Kickoff type",
                        border_style="cyan",
                    )
                )
            choices = [
                Choice("Regular kickoff", "kick_regular"),
                Choice("Onside kick", "kick_onside"),
                Separator("─" * 48),
            ]
            choices.extend(meta)
            pick = questionary.select("Regular kickoff or onside attempt?", choices=choices, style=_Q_STYLE).ask()
            if pick is None:
                return None
            m = _dispatch_meta(str(pick))
            if m:
                return m
            if pick == "kick_regular":
                return ("event", ChooseKickoffKind(onside=False))
            if pick == "kick_onside":
                return ("event", ChooseKickoffKind(onside=True))
            return None
        ev = _flow_kickoff(console, rules, state)
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.ONSIDE_KICK:
        ev = _flow_onside_kick(console, rules, state)
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.KICKOFF_RUN_OR_SPOT:
        console.print(
            Panel(
                dart_help.kickoff_run_or_spot_instructions(rules, state),
                title="After the kick",
                border_style="cyan",
            )
        )
        line = state.kickoff_pending_touchback_line
        tb_label = f"Take ball at own {line}" if line is not None else "Take touchback"
        choices = [
            Choice(tb_label, "tb"),
            Choice("Run out from goal line", "runout"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("How does the receiving team take the ball?", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "tb":
            return ("event", ChooseKickoffTouchbackOrRun(take_touchback=True))
        if pick == "runout":
            return ("event", ChooseKickoffTouchbackOrRun(take_touchback=False))
        return None

    if phase is Phase.KICKOFF_RUN_OUT_DART:
        ev = _flow_kickoff_run_out(console, rules, state)
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.KICKOFF_RETURN_DART:
        ev = _flow_kickoff_return(console, rules, state)
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.SCRIMMAGE_OFFENSE:
        console.print(
            Panel(
                "Scrimmage dart, or punt / field goal when allowed.",
                title="Offense",
                border_style="cyan",
            )
        )
        choices = [
            Choice("Scrimmage play", "off_scrim"),
        ]
        if state.downs.down >= 2:
            choices.append(Choice("Punt", "fd_punt"))
        fg_on_allowed_down = state.downs.down in (3, 4) or state.last_play_of_period
        if fg_on_allowed_down and _fg_in_range(state, rules):
            choices.append(Choice("Field goal", "fd_fg"))
        choices.append(Separator("─" * 48))
        choices.extend(meta)
        pick = questionary.select("What do you call?", choices=choices, style=_Q_STYLE).ask()
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
        _print_defense_instructions_panel(console, rules, state)
        choices = [
            Choice("Numbered wedge", "wedge"),
            Choice("Green bull", "green"),
            Choice("Red bull", "red"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Where did the dart land?", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        ps = str(pick)
        if ps.startswith("meta_"):
            return _dispatch_meta(ps)
        if ps not in ("wedge", "green", "red"):
            return None
        ev = _finish_scrimmage_defense_after_hit_kind(
            console,
            rules,
            state,
            cast(Literal["wedge", "green", "red"], ps),
        )
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.SCRIMMAGE_STRIP_DART:
        ev = _flow_scrimmage_strip_dart(console, rules, state)
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.FOURTH_DOWN_DECISION:
        console.print(
            Panel("Fourth down — go for it, punt, or field goal.", title="4th down", border_style="cyan")
        )
        choices = [
            Choice("Go for it", "fd_go"),
            Choice("Punt", "fd_punt"),
            Choice("Field goal", "fd_fg"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("What do you call on 4th down?", choices=choices, style=_Q_STYLE).ask()
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

    if phase is Phase.FIELD_GOAL_OFFENSE_DART:
        choices = [
            Choice("Record kicker's field goal dart", "go"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Field goal attempt", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "go":
            ev = _flow_field_goal_offense_dart(console, rules, state)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.FIELD_GOAL_GREEN_CHOICE:
        console.print(
            Panel(
                dart_help.field_goal_green_choice_instructions(state, rules),
                title="Field goal — after green bull",
                border_style="cyan",
            )
        )
        choices = [
            Choice("Real field goal (then defense dart)", "fg_real"),
            Choice("Fake field goal (yardage dart, then defense)", "fg_fake"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Real kick or fake?", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "fg_real":
            return ("event", ChooseFieldGoalAfterGreen(real_kick=True))
        if pick == "fg_fake":
            return ("event", ChooseFieldGoalAfterGreen(real_kick=False))
        return None

    if phase is Phase.FIELD_GOAL_FAKE_OFFENSE:
        choices = [
            Choice("Record fake field goal yardage dart", "go"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Fake field goal", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "go":
            ev = _flow_field_goal_fake_offense(console, rules, state)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.FIELD_GOAL_DEFENSE:
        console.print(
            Panel(
                dart_help.field_goal_defense_instructions(state, rules),
                title="Field goal — defense",
                border_style="cyan",
            )
        )
        choices = [
            Choice("Numbered wedge", "wedge"),
            Choice("Green bull", "green"),
            Choice("Red bull", "red"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Where did the defense dart land?", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        ps = str(pick)
        if ps.startswith("meta_"):
            return _dispatch_meta(ps)
        if ps not in ("wedge", "green", "red"):
            return None
        ev = _finish_field_goal_defense_after_hit_kind(
            console,
            rules,
            state,
            cast(Literal["wedge", "green", "red"], ps),
        )
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.PUNT_ATTEMPT:
        choices = [
            Choice("Record punt dart", "go"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Ready to record the punt dart?", choices=choices, style=_Q_STYLE).ask()
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

    if phase is Phase.AFTER_TOUCHDOWN_CHOICE:
        console.print(
            Panel(
                "Choose a one-point kick or a two-point try.",
                title="After touchdown",
                border_style="cyan",
            )
        )
        choices = [
            Choice("Extra point (one point)", "td_ep"),
            Choice("Two-point conversion", "td_2pt"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Which try after the touchdown?", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "td_ep":
            return ("event", ChooseExtraPointOrTwo(extra_point=True))
        if pick == "td_2pt":
            return ("event", ChooseExtraPointOrTwo(extra_point=False))
        return None

    if phase is Phase.EXTRA_POINT_ATTEMPT:
        console.print(
            Panel(
                dart_help.extra_point_attempt_instructions(rules, state),
                title="Extra point",
                border_style="cyan",
            )
        )
        choices = [
            Choice("Good", "xpa_good"),
            Choice("No good (miss)", "xpa_bad"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Was the extra point good?", choices=choices, style=_Q_STYLE).ask()
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
        console.print(
            Panel(dart_help.two_point_instructions(rules, state), title="Two point conversion", border_style="cyan")
        )
        choices = [
            Choice("Good", "tpc_good"),
            Choice("No good (miss)", "tpc_bad"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Was the two point conversion good?", choices=choices, style=_Q_STYLE).ask()
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

    if phase is Phase.SAFETY_SEQUENCE:
        console.print(
            Panel(
                dart_help.safety_sequence_instructions(state, rules),
                title="Safety",
                border_style="magenta",
            )
        )
        choices = [
            Choice("Continue to safety free kick (kickoff phase)", "safety_go"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Safety — next step", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "safety_go":
            return ("event", ConfirmSafetyKickoff())
        return None

    if phase is Phase.OVERTIME_START:
        console.print(
            Panel(
                dart_help.overtime_start_instructions(state, rules),
                title="Overtime",
                border_style="magenta",
            )
        )
        choices = [
            Choice("Record overtime coin toss", "ot_toss"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select("Overtime", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        m = _dispatch_meta(str(pick))
        if m:
            return m
        if pick == "ot_toss":
            ev = _flow_coin_toss_menu(console, rules)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.GAME_OVER:
        choices = list(meta)
        pick = questionary.select("Pick an action:", choices=choices, style=_Q_STYLE).ask()
        if pick is None:
            return None
        return _dispatch_meta(str(pick))

    console.print(f"[yellow]Phase {phase.value} has no play menu yet.[/yellow]")
    choices = list(meta)
    pick = questionary.select("Pick an action:", choices=choices, style=_Q_STYLE).ask()
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
    if tag == "meta_timeout":
        return ("meta", "timeout")
    return None
