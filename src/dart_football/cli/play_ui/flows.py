"""Phase-specific dart/outcome collection flows."""

from __future__ import annotations

from typing import Literal

import questionary
from questionary import Choice
from rich.console import Console
from rich.panel import Panel

from dart_football.cli.play_ui.shared import (
    QUESTIONARY_STYLE,
    collect_offense_rings,
    prompt_hit_kind,
    read_int,
)
from dart_football.display import dart_help
from dart_football.engine.events import (
    FieldGoalDefenseDart,
    FieldGoalFakeOffenseDart,
    FieldGoalOffenseDart,
    KickoffKick,
    KickoffReturnKick,
    KickoffRunOutKick,
    PuntKick,
    ScrimmageDefense,
    ScrimmageOffense,
    ScrimmageStripDart,
)
from dart_football.engine.state import GameState
from dart_football.rules.schema import RuleSet


def prompt_kickoff_dart(
    console: Console,
    rules: RuleSet,
    state: GameState,
    *,
    panel_title: str,
    instructions: str,
) -> KickoffKick | None:
    console.print(Panel(instructions, title=panel_title, border_style="cyan"))
    hk = prompt_hit_kind(console)
    if hk is None:
        return None
    if hk == "green":
        return KickoffKick(segment=rules.scrimmage.bull_green_segment, bull="green")
    if hk == "red":
        return KickoffKick(segment=rules.scrimmage.bull_red_segment, bull="red")
    lo, hi = rules.kickoff.segment_min, rules.kickoff.segment_max
    seg = read_int(console, f"Wedge number ({lo}–{hi}): ", lo, hi)
    if seg is None:
        return None
    return KickoffKick(segment=seg, bull="none")


def prompt_kickoff_event(console: Console, rules: RuleSet, state: GameState) -> KickoffKick | None:
    return prompt_kickoff_dart(
        console,
        rules,
        state,
        panel_title="Kickoff — read the board",
        instructions=dart_help.kickoff_instructions(rules, state),
    )


def prompt_onside_kick_event(
    console: Console, rules: RuleSet, state: GameState
) -> KickoffKick | None:
    return prompt_kickoff_dart(
        console,
        rules,
        state,
        panel_title="Onside kick — read the board",
        instructions=dart_help.onside_kick_instructions(rules, state),
    )


def prompt_kickoff_run_out_event(
    console: Console, rules: RuleSet, state: GameState
) -> KickoffRunOutKick | None:
    console.print(
        Panel(
            dart_help.kickoff_run_out_instructions(rules, state),
            title="Run out — read the board",
            border_style="cyan",
        )
    )
    hk = prompt_hit_kind(console)
    if hk is None:
        return None
    if hk == "green":
        return KickoffRunOutKick(segment=rules.scrimmage.bull_green_segment, bull="green")
    if hk == "red":
        return KickoffRunOutKick(segment=rules.scrimmage.bull_red_segment, bull="red")
    lo, hi = rules.kickoff.segment_min, rules.kickoff.segment_max
    seg = read_int(console, f"Wedge number ({lo}–{hi}): ", lo, hi)
    if seg is None:
        return None
    return KickoffRunOutKick(segment=seg, bull="none")


def prompt_kickoff_return_event(
    console: Console, rules: RuleSet, state: GameState
) -> KickoffReturnKick | None:
    console.print(
        Panel(
            dart_help.kickoff_return_instructions(rules, state),
            title="Kickoff return — read the board",
            border_style="cyan",
        )
    )
    hk = prompt_hit_kind(console)
    if hk is None:
        return None
    sc = rules.scrimmage
    if hk == "green":
        return KickoffReturnKick(segment=sc.bull_green_segment, bull="green")
    if hk == "red":
        return KickoffReturnKick(segment=sc.bull_red_segment, bull="red")
    seg = read_int(
        console,
        f"Wedge number ({sc.segment_min}–{sc.segment_max}): ",
        sc.segment_min,
        sc.segment_max,
    )
    if seg is None:
        return None
    if 13 <= seg <= 20:
        rings = collect_offense_rings(console)
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


def prompt_scrimmage_offense_event(
    console: Console, rules: RuleSet, state: GameState
) -> ScrimmageOffense | None:
    console.print(
        Panel(
            dart_help.scrimmage_offense_instructions(rules, state),
            title="Offense — read the board",
            border_style="cyan",
        )
    )
    hk = prompt_hit_kind(console)
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
    seg = read_int(
        console,
        f"Wedge number ({sc.segment_min}–{sc.segment_max}): ",
        sc.segment_min,
        sc.segment_max,
    )
    if seg is None:
        return None
    rings = collect_offense_rings(console)
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


def print_defense_instructions_panel(console: Console, rules: RuleSet, state: GameState) -> None:
    console.print(
        Panel(
            dart_help.scrimmage_defense_instructions(rules, state),
            title="Defense — read the board",
            border_style="cyan",
        )
    )


def finish_scrimmage_defense_after_hit_kind(
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
    seg = read_int(
        console,
        f"Wedge number ({sc.segment_min}–{sc.segment_max}): ",
        sc.segment_min,
        sc.segment_max,
    )
    if seg is None:
        return None
    return ScrimmageDefense(
        segment=seg, bull="none", double_ring=False, triple_ring=False, triple_inner=None
    )


def prompt_field_goal_offense_dart_event(
    console: Console, rules: RuleSet, state: GameState
) -> FieldGoalOffenseDart | None:
    console.print(
        Panel(
            dart_help.field_goal_offense_dart_instructions(state, rules),
            title="Field goal — kicker",
            border_style="cyan",
        )
    )
    hk = prompt_hit_kind(console)
    if hk is None:
        return None
    sc = rules.scrimmage
    if hk == "green":
        return FieldGoalOffenseDart(zone="green", segment=sc.bull_green_segment)
    if hk == "red":
        return FieldGoalOffenseDart(zone="red", segment=sc.bull_red_segment)
    seg = read_int(
        console,
        f"Wedge number ({sc.segment_min}–{sc.segment_max}): ",
        sc.segment_min,
        sc.segment_max,
    )
    if seg is None:
        return None
    loc = questionary.select(
        "Where did it land for field goal rules?",
        choices=[
            Choice(
                "Inside the triple ring — single/double between double and triple (not on triple scoring)",
                "inner",
            ),
            Choice("On the triple scoring ring", "triple"),
            Choice("Outside the triple ring — outer wedge toward the double ring", "outside"),
        ],
        style=QUESTIONARY_STYLE,
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


def prompt_field_goal_fake_offense_event(
    console: Console, rules: RuleSet, state: GameState
) -> FieldGoalFakeOffenseDart | None:
    console.print(
        Panel(
            dart_help.field_goal_fake_offense_instructions(state, rules),
            title="Fake field goal",
            border_style="cyan",
        )
    )
    hk = prompt_hit_kind(console)
    if hk is None:
        return None
    sc = rules.scrimmage
    if hk == "green":
        return FieldGoalFakeOffenseDart(segment=sc.bull_green_segment, bull="green")
    if hk == "red":
        return FieldGoalFakeOffenseDart(segment=sc.bull_red_segment, bull="red")
    seg = read_int(
        console,
        f"Wedge number ({sc.segment_min}–{sc.segment_max}): ",
        sc.segment_min,
        sc.segment_max,
    )
    if seg is None:
        return None
    rings = collect_offense_rings(console)
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


def finish_field_goal_defense_after_hit_kind(
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
    seg = read_int(
        console,
        f"Wedge number ({sc.segment_min}–{sc.segment_max}): ",
        sc.segment_min,
        sc.segment_max,
    )
    if seg is None:
        return None
    rings = collect_offense_rings(console)
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


def prompt_scrimmage_strip_dart_event(
    console: Console, rules: RuleSet, state: GameState
) -> ScrimmageStripDart | None:
    console.print(
        Panel(
            dart_help.scrimmage_strip_instructions(rules, state),
            title="Strip dart — numbered wedge only",
            border_style="cyan",
        )
    )
    sc = rules.scrimmage
    seg = read_int(
        console,
        f"Wedge number ({sc.segment_min}–{sc.segment_max}): ",
        sc.segment_min,
        sc.segment_max,
    )
    if seg is None:
        return None
    return ScrimmageStripDart(segment=seg)


def prompt_punt_event(console: Console, rules: RuleSet, state: GameState) -> PuntKick | None:
    console.print(
        Panel(
            dart_help.punt_instructions(rules, state),
            title="Punt — read the board",
            border_style="cyan",
        )
    )
    hk = prompt_hit_kind(console)
    if hk is None:
        return None
    if hk == "green":
        return PuntKick(segment=rules.scrimmage.bull_green_segment, bull="green")
    if hk == "red":
        return PuntKick(segment=rules.scrimmage.bull_red_segment, bull="red")
    pr = rules.punt
    seg = read_int(
        console,
        f"Wedge number ({pr.segment_min}–{pr.segment_max}): ",
        pr.segment_min,
        pr.segment_max,
    )
    if seg is None:
        return None
    return PuntKick(segment=seg, bull="none")
