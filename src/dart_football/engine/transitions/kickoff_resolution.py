from __future__ import annotations

from dataclasses import replace

from dart_football.display.formatting import format_possession_summary
from dart_football.engine.events import KickoffKick, KickoffReturnKick, KickoffRunOutKick
from dart_football.engine.phases import Phase
from dart_football.engine.state import DownAndDistance, FieldPosition, GameState, TeamId
from dart_football.engine.transitions.clock_and_timeouts import kickoff_resolve_timeout_state
from dart_football.engine.transitions.field_geometry import (
    field_from_spot_band,
    kickoff_green_bull_recovery_field,
    match_spot_band_for_segment,
    receiver_goal_line_field_position,
)
from dart_football.engine.transitions.scoring_setup import state_after_touchdown
from dart_football.engine.transitions.types import TransitionError, TransitionOk
from dart_football.rules.schema import RuleSet


def finish_kickoff_to_scrimmage(
    state: GameState,
    rules: RuleSet,
    receiver: TeamId,
    field: FieldPosition,
    summary: str,
) -> TransitionOk:
    st = kickoff_resolve_timeout_state(state)
    downs = DownAndDistance(down=1, to_go=10, los_yard=field.scrimmage_line)
    s = replace(
        st,
        offense=receiver,
        field=field,
        downs=downs,
        clock=st.clock,
        kickoff_kicker=None,
        kickoff_receiver=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        scrimmage_pending_offense_yards=None,
        last_touchdown_team=None,
        declared_onside=False,
    )
    return TransitionOk(
        s,
        Phase.SCRIMMAGE_OFFENSE,
        f"{summary} — {format_possession_summary(s)}",
    )


def finish_kickoff_return_touchdown(
    state: GameState,
    receiver: TeamId,
    rules: RuleSet,
    summary: str,
) -> TransitionOk:
    st = kickoff_resolve_timeout_state(state)
    s2 = replace(
        st,
        kickoff_kicker=None,
        kickoff_receiver=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        declared_onside=False,
        scrimmage_pending_offense_yards=None,
    )
    s_td = state_after_touchdown(s2, receiver, rules)
    return TransitionOk(
        s_td,
        Phase.AFTER_TOUCHDOWN_CHOICE,
        f"{summary} — TD {receiver.value}! (+{rules.scoring.touchdown})",
    )


def run_out_net_yards(event: KickoffRunOutKick, rules: RuleSet) -> int | None:
    """Return net return yards toward the goal, or None if receiving-team TD."""
    if event.bull == "green":
        return 50
    if event.bull == "red":
        return None
    seg = event.segment
    if seg < rules.kickoff.segment_min or seg > rules.kickoff.segment_max:
        raise ValueError("segment out of range")
    if 1 <= seg <= 12:
        return 25
    if 13 <= seg <= 20:
        return seg * 2
    raise ValueError("segment out of range")


def return_dart_net_yards(event: KickoffReturnKick, rules: RuleSet) -> int | None:
    if event.bull == "green":
        return 50
    if event.bull == "red":
        return None
    seg = event.segment
    sc = rules.scrimmage
    if seg < sc.segment_min or seg > sc.segment_max:
        raise ValueError("segment out of range")
    if 1 <= seg <= 12:
        return 12
    if 13 <= seg <= 20:
        mult = 1
        if event.triple_ring:
            mult *= sc.triple_multiplier
        if event.double_ring:
            mult *= sc.double_multiplier
        return seg * mult
    raise ValueError("segment out of range")


def apply_kickoff_dart(
    state: GameState,
    event: KickoffKick,
    rules: RuleSet,
    *,
    onside_attempt: bool,
) -> TransitionOk | TransitionError:
    """Resolve kick dart (regular or onside); may enter run/return follow-up before scrimmage."""
    kicker = state.kickoff_kicker
    receiver = state.kickoff_receiver
    assert kicker is not None and receiver is not None
    label = "Onside kick" if onside_attempt else "Kickoff"

    if event.bull == "green":
        st = kickoff_resolve_timeout_state(state)
        field = kickoff_green_bull_recovery_field(kicker)
        downs = DownAndDistance(down=1, to_go=10, los_yard=field.scrimmage_line)
        s = replace(
            st,
            offense=kicker,
            field=field,
            downs=downs,
            clock=st.clock,
            kickoff_kicker=None,
            kickoff_receiver=None,
            kickoff_awaiting="none",
            kickoff_pending_touchback_line=None,
            scrimmage_pending_offense_yards=None,
            last_touchdown_team=None,
            declared_onside=False,
        )
        return TransitionOk(
            s,
            Phase.SCRIMMAGE_OFFENSE,
            f"{label} green bull: receiving fumble — kicking team ball at opponent 35",
        )

    if event.bull == "red":
        st = kickoff_resolve_timeout_state(state)
        s2 = replace(
            st,
            kickoff_kicker=None,
            kickoff_receiver=None,
            kickoff_awaiting="none",
            kickoff_pending_touchback_line=None,
            declared_onside=False,
        )
        s_td = state_after_touchdown(s2, kicker, rules)
        return TransitionOk(
            s_td,
            Phase.AFTER_TOUCHDOWN_CHOICE,
            f"{label} red bull: receiving fumble — touchdown {kicker.value} (+{rules.scoring.touchdown})",
        )

    seg = event.segment
    if seg < rules.kickoff.segment_min or seg > rules.kickoff.segment_max:
        return TransitionError(
            f"segment must be {rules.kickoff.segment_min}..{rules.kickoff.segment_max}",
            ("KickoffKick",),
        )
    band = match_spot_band_for_segment(rules.kickoff.bands, seg)
    if band is None:
        return TransitionError(f"no kickoff band for segment {seg}", ("KickoffKick",))

    if not onside_attempt and band.kind == "touchback" and band.allow_runout_choice:
        assert band.touchback_line is not None
        goal = receiver_goal_line_field_position(receiver)
        downs = DownAndDistance(1, 10, goal.scrimmage_line)
        s = replace(
            state,
            offense=receiver,
            field=goal,
            downs=downs,
            kickoff_awaiting="run_or_spot",
            kickoff_pending_touchback_line=band.touchback_line,
            declared_onside=False,
        )
        return TransitionOk(
            s,
            Phase.KICKOFF_RUN_OR_SPOT,
            f"{label} wedge {seg} — take ball at own {band.touchback_line} or run out from goal line",
        )

    if not onside_attempt and band.kind == "wedge_times" and band.requires_return_dart:
        field = field_from_spot_band(receiver, band, seg)
        downs = DownAndDistance(1, 10, field.scrimmage_line)
        s = replace(
            state,
            offense=receiver,
            field=field,
            downs=downs,
            kickoff_awaiting="return_dart",
            kickoff_pending_touchback_line=None,
            declared_onside=False,
        )
        return TransitionOk(
            s,
            Phase.KICKOFF_RETURN_DART,
            f"{label} wedge {seg} — return dart from kick spot ({format_possession_summary(s)})",
        )

    st = kickoff_resolve_timeout_state(state)
    field = field_from_spot_band(receiver, band, seg)
    downs = DownAndDistance(down=1, to_go=10, los_yard=field.scrimmage_line)
    s = replace(
        st,
        offense=receiver,
        field=field,
        downs=downs,
        clock=st.clock,
        kickoff_kicker=None,
        kickoff_receiver=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        scrimmage_pending_offense_yards=None,
        last_touchdown_team=None,
        declared_onside=False,
    )
    summary = f"{label} wedge {seg} → {format_possession_summary(s)}"
    return TransitionOk(s, Phase.SCRIMMAGE_OFFENSE, summary)
