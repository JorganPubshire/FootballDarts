from __future__ import annotations

from dataclasses import replace
from typing import Literal

from dart_football.display.formatting import opponent
from dart_football.engine.events import ScrimmageDefense
from dart_football.engine.phases import Phase
from dart_football.engine.state import DownAndDistance, FieldPosition, GameState
from dart_football.engine.transitions.clock_and_timeouts import advance_clock_for_scrimmage_play
from dart_football.engine.transitions.field_geometry import (
    is_safety_field,
    is_touchdown_field,
    turnover_on_downs_state,
    yards_to_goal_line,
)
from dart_football.engine.transitions.scoring_setup import state_after_touchdown
from dart_football.engine.transitions.types import TransitionOk
from dart_football.rules.schema import RuleSet

# Standard dartboard: clockwise from top; adjacent wedges alternate black/cream.
WEDGE_ORDER_CLOCKWISE = (
    20,
    1,
    18,
    4,
    13,
    6,
    10,
    15,
    2,
    17,
    3,
    19,
    7,
    16,
    8,
    11,
    14,
    9,
    12,
    5,
)


def effective_segment_with_bull(
    segment: int,
    bull: Literal["none", "green", "red"],
    rules: RuleSet,
) -> int:
    if bull == "green":
        return rules.scrimmage.bull_green_segment
    if bull == "red":
        return rules.scrimmage.bull_red_segment
    return segment


def wedge_board_color_parity(segment: int) -> int:
    return WEDGE_ORDER_CLOCKWISE.index(segment) % 2


def wedge_board_colors_match(offense_eff: int, defense_segment: int) -> bool:
    return wedge_board_color_parity(offense_eff) == wedge_board_color_parity(defense_segment)


def defensive_touchdown_after_offense_yards(
    state: GameState, rules: RuleSet, off_yards: int, summary_prefix: str
) -> TransitionOk:
    new_clock, st = advance_clock_for_scrimmage_play(state, rules)
    s_inter = replace(
        st,
        clock=new_clock,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
    )
    scoring = opponent(state.offense)
    s_td = state_after_touchdown(s_inter, scoring, rules)
    return TransitionOk(
        s_td,
        Phase.AFTER_TOUCHDOWN_CHOICE,
        f"{summary_prefix} — defensive TD {scoring.value}! (+{rules.scoring.touchdown})",
    )


def no_gain_advance_down(
    state_after_clock: GameState,
    state_before_play: GameState,
    field: FieldPosition,
    summary: str,
) -> TransitionOk:
    down = state_before_play.downs.down + 1
    to_go = state_before_play.downs.to_go
    if down > 4:
        s_to = turnover_on_downs_state(state_after_clock, field)
        return TransitionOk(
            s_to,
            Phase.SCRIMMAGE_OFFENSE,
            f"{summary} | turnover on downs",
        )
    downs = DownAndDistance(down, to_go, field.scrimmage_line)
    s_final = replace(state_after_clock, downs=downs, field=field)
    next_phase = Phase.FOURTH_DOWN_DECISION if down == 4 else Phase.SCRIMMAGE_OFFENSE
    return TransitionOk(s_final, next_phase, f"{summary} | down {down} & {to_go}")


def finish_scrimmage_net_play(
    state_before: GameState,
    rules: RuleSet,
    s_inter: GameState,
    new_field: FieldPosition,
    off_yards: int,
    def_yards: int,
    net: int,
    dn: str,
) -> TransitionOk:
    if is_touchdown_field(new_field):
        scoring = state_before.offense
        s_td = state_after_touchdown(s_inter, scoring, rules)
        return TransitionOk(
            s_td,
            Phase.AFTER_TOUCHDOWN_CHOICE,
            f"Play: off {off_yards} vs def {def_yards}{dn} → net {net} yds | TD {scoring.value}! (+{rules.scoring.touchdown})",
        )
    if is_safety_field(new_field):
        defense_scored = opponent(state_before.offense)
        s_safe = replace(
            s_inter,
            field=new_field,
            downs=DownAndDistance(
                1, min(10, yards_to_goal_line(new_field)), new_field.scrimmage_line
            ),
            scores=s_inter.scores.add(defense_scored, rules.scoring.safety),
            safety_pending_kicker=state_before.offense,
            scrimmage_pending_offense_yards=None,
            scrimmage_pending_offense_kind="none",
            scrimmage_pending_offense_eff_segment=None,
        )
        return TransitionOk(
            s_safe,
            Phase.SAFETY_SEQUENCE,
            f"Safety! {defense_scored.value} +{rules.scoring.safety} — confirm free kick when ready",
        )
    dist = yards_to_goal_line(new_field)
    to_go_before = state_before.downs.to_go
    if net >= to_go_before:
        down = 1
        to_go = min(10, dist)
    else:
        down = state_before.downs.down + 1
        to_go = to_go_before - net
    if down > 4:
        s_to = turnover_on_downs_state(s_inter, new_field)
        return TransitionOk(
            s_to,
            Phase.SCRIMMAGE_OFFENSE,
            f"Play: net {net} yds{dn} | turnover on downs",
        )
    downs = DownAndDistance(down, to_go, new_field.scrimmage_line)
    s_final = replace(s_inter, downs=downs)
    next_phase = Phase.FOURTH_DOWN_DECISION if down == 4 else Phase.SCRIMMAGE_OFFENSE
    return TransitionOk(
        s_final,
        next_phase,
        f"Play: off {off_yards} vs def {def_yards}{dn} → net {net} yds | down {down} & {to_go}",
    )


def defense_ring_note(event: ScrimmageDefense) -> str:
    if event.bull != "none":
        return f" (def bull {event.bull})"
    parts: list[str] = []
    if event.double_ring:
        parts.append("D")
    if event.triple_ring:
        t = "T"
        if event.triple_inner is True:
            t += " in"
        elif event.triple_inner is False:
            t += " out"
        parts.append(t)
    if not parts:
        return ""
    return f" [{'/'.join(parts)} log]"
