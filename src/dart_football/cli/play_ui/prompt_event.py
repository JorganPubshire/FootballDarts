"""Top-level play prompt: phase menus and dispatch into flow helpers."""

from __future__ import annotations

from typing import Literal, cast

import questionary
from questionary import Choice, Separator
from rich.console import Console
from rich.panel import Panel

from dart_football.cli.play_ui.flows import (
    finish_field_goal_defense_after_hit_kind,
    finish_scrimmage_defense_after_hit_kind,
    print_defense_instructions_panel,
    prompt_field_goal_fake_offense_event,
    prompt_field_goal_offense_dart_event,
    prompt_kickoff_event,
    prompt_kickoff_return_event,
    prompt_kickoff_run_out_event,
    prompt_onside_kick_event,
    prompt_punt_event,
    prompt_scrimmage_offense_event,
    prompt_scrimmage_strip_dart_event,
)
from dart_football.cli.play_ui.shared import (
    QUESTIONARY_STYLE,
    MetaAction,
    field_goal_attempt_allowed,
    field_goal_choice_available,
    meta_choices_for_phase,
    prompt_coin_toss_menu,
)
from dart_football.display import dart_help, team_display_name
from dart_football.engine.events import (
    ChooseExtraPointOrTwo,
    ChooseFieldGoalAfterGreen,
    ChooseKickoffKind,
    ChooseKickoffTouchbackOrRun,
    ChooseKickOrReceive,
    ConfirmSafetyKickoff,
    Event,
    ExtraPointOutcome,
    FourthDownChoice,
    TwoPointOutcome,
)
from dart_football.engine.phases import Phase
from dart_football.engine.state import GameState
from dart_football.rules.schema import RuleSet

ActionPick = tuple[Literal["event"], Event] | tuple[Literal["meta"], MetaAction]


def dispatch_meta_action(tag: str) -> ActionPick | None:
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


def prompt_play_event(
    console: Console,
    phase: Phase,
    rules: RuleSet,
    state: GameState,
) -> ActionPick | None:
    """Top-level 'Select a play' menu, then phase-specific dart/outcome collection."""
    meta = meta_choices_for_phase(phase)

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
        pick = questionary.select(
            "What do you want to do?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
        if m:
            return m
        if pick == "start_game":
            ev = prompt_coin_toss_menu(console, rules)
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
        pick = questionary.select(
            "Kick off or receive?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        if str(pick).startswith("meta_"):
            return dispatch_meta_action(str(pick))
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
            pick = questionary.select(
                "Regular kickoff or onside attempt?", choices=choices, style=QUESTIONARY_STYLE
            ).ask()
            if pick is None:
                return None
            m = dispatch_meta_action(str(pick))
            if m:
                return m
            if pick == "kick_regular":
                return ("event", ChooseKickoffKind(onside=False))
            if pick == "kick_onside":
                return ("event", ChooseKickoffKind(onside=True))
            return None
        ev = prompt_kickoff_event(console, rules, state)
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.ONSIDE_KICK:
        ev = prompt_onside_kick_event(console, rules, state)
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
        pick = questionary.select(
            "How does the receiving team take the ball?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
        if m:
            return m
        if pick == "tb":
            return ("event", ChooseKickoffTouchbackOrRun(take_touchback=True))
        if pick == "runout":
            return ("event", ChooseKickoffTouchbackOrRun(take_touchback=False))
        return None

    if phase is Phase.KICKOFF_RUN_OUT_DART:
        ev = prompt_kickoff_run_out_event(console, rules, state)
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.KICKOFF_RETURN_DART:
        ev = prompt_kickoff_return_event(console, rules, state)
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
        if field_goal_choice_available(state, rules):
            choices.append(Choice("Field goal", "fd_fg"))
        choices.append(Separator("─" * 48))
        choices.extend(meta)
        pick = questionary.select(
            "What do you call?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
        if m:
            return m
        if pick == "fd_punt":
            return ("event", FourthDownChoice(kind="punt"))
        if pick == "fd_fg":
            return ("event", FourthDownChoice(kind="field_goal"))
        if pick == "off_scrim":
            ev = prompt_scrimmage_offense_event(console, rules, state)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.SCRIMMAGE_DEFENSE:
        print_defense_instructions_panel(console, rules, state)
        choices = [
            Choice("Numbered wedge", "wedge"),
            Choice("Green bull", "green"),
            Choice("Red bull", "red"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select(
            "Where did the dart land?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        ps = str(pick)
        if ps.startswith("meta_"):
            return dispatch_meta_action(ps)
        if ps not in ("wedge", "green", "red"):
            return None
        ev = finish_scrimmage_defense_after_hit_kind(
            console,
            rules,
            state,
            cast(Literal["wedge", "green", "red"], ps),
        )
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.SCRIMMAGE_STRIP_DART:
        ev = prompt_scrimmage_strip_dart_event(console, rules, state)
        if ev is None:
            return None
        return ("event", ev)

    if phase is Phase.FOURTH_DOWN_DECISION:
        fg_ok = field_goal_attempt_allowed(state, rules)
        panel_body = (
            "Fourth down — scrimmage play, punt, or field goal."
            if fg_ok
            else (
                f"Fourth down — scrimmage play or punt. "
                f"No field goal from this spot (must be within {rules.field_goal.max_distance_yards} yards "
                "of the goal, with the ruleset’s 60-yard attempt restrictions)."
            )
        )
        console.print(
            Panel(
                panel_body,
                title="4th down",
                border_style="cyan",
            )
        )
        choices = [
            Choice("Scrimmage play", "off_scrim"),
            Choice("Punt", "fd_punt"),
        ]
        if fg_ok:
            choices.append(Choice("Field goal", "fd_fg"))
        choices.append(Separator("─" * 48))
        choices.extend(meta)
        pick = questionary.select(
            "What do you call on 4th down?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
        if m:
            return m
        if pick == "off_scrim":
            ev = prompt_scrimmage_offense_event(console, rules, state)
            if ev is None:
                return None
            return ("event", ev)
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
        pick = questionary.select(
            "Field goal attempt", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
        if m:
            return m
        if pick == "go":
            ev = prompt_field_goal_offense_dart_event(console, rules, state)
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
        pick = questionary.select(
            "Real kick or fake?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
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
        pick = questionary.select("Fake field goal", choices=choices, style=QUESTIONARY_STYLE).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
        if m:
            return m
        if pick == "go":
            ev = prompt_field_goal_fake_offense_event(console, rules, state)
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
        pick = questionary.select(
            "Where did the defense dart land?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        ps = str(pick)
        if ps.startswith("meta_"):
            return dispatch_meta_action(ps)
        if ps not in ("wedge", "green", "red"):
            return None
        ev = finish_field_goal_defense_after_hit_kind(
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
        pick = questionary.select(
            "Ready to record the punt dart?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
        if m:
            return m
        if pick == "go":
            ev = prompt_punt_event(console, rules, state)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.AFTER_TOUCHDOWN_CHOICE:
        console.print(
            Panel(
                "Choose a one-point kick or a two-point conversion.",
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
        pick = questionary.select(
            "Which try after the touchdown?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
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
        pick = questionary.select(
            "Was the extra point good?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
        if m:
            return m
        if pick == "xpa_good":
            return ("event", ExtraPointOutcome(good=True))
        if pick == "xpa_bad":
            return ("event", ExtraPointOutcome(good=False))
        return None

    if phase is Phase.TWO_POINT_ATTEMPT:
        console.print(
            Panel(
                dart_help.two_point_instructions(rules, state),
                title="Two point conversion",
                border_style="cyan",
            )
        )
        choices = [
            Choice("Good", "tpc_good"),
            Choice("No good (miss)", "tpc_bad"),
            Separator("─" * 48),
        ]
        choices.extend(meta)
        pick = questionary.select(
            "Was the two point conversion good?", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
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
        pick = questionary.select(
            "Safety — next step", choices=choices, style=QUESTIONARY_STYLE
        ).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
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
        pick = questionary.select("Overtime", choices=choices, style=QUESTIONARY_STYLE).ask()
        if pick is None:
            return None
        m = dispatch_meta_action(str(pick))
        if m:
            return m
        if pick == "ot_toss":
            ev = prompt_coin_toss_menu(console, rules)
            if ev is None:
                return None
            return ("event", ev)
        return None

    if phase is Phase.GAME_OVER:
        choices = list(meta)
        pick = questionary.select("Pick an action:", choices=choices, style=QUESTIONARY_STYLE).ask()
        if pick is None:
            return None
        return dispatch_meta_action(str(pick))

    console.print(f"[yellow]Phase {phase.value} has no play menu yet.[/yellow]")
    choices = list(meta)
    pick = questionary.select("Pick an action:", choices=choices, style=QUESTIONARY_STYLE).ask()
    if pick is None:
        return None
    return dispatch_meta_action(str(pick))
