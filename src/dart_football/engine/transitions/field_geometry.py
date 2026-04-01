from __future__ import annotations

from dataclasses import replace

from dart_football.display.formatting import opponent
from dart_football.engine.state import DownAndDistance, FieldPosition, GameState, TeamId
from dart_football.rules.schema import KickoffBand, ScrimmageYardBand


def kickoff_tee_field_position(kicker: TeamId) -> FieldPosition:
    """Kickoff spotted at the kicker's 35-yard line (NFL-style)."""
    if kicker is TeamId.RED:
        return FieldPosition(35, 100)
    return FieldPosition(65, 0)


def kickoff_tee_down_and_distance(kicker: TeamId) -> DownAndDistance:
    fp = kickoff_tee_field_position(kicker)
    return DownAndDistance(1, 10, fp.scrimmage_line)


def field_spot_from_own_yard(receiver: TeamId, own_yard: int) -> FieldPosition:
    if own_yard < 1 or own_yard > 99:
        raise ValueError("own_yard must be 1..99")
    if receiver is TeamId.RED:
        return FieldPosition(scrimmage_line=own_yard, goal_yard=100)
    return FieldPosition(scrimmage_line=100 - own_yard, goal_yard=0)


def field_from_spot_band(receiver: TeamId, band: KickoffBand, segment: int) -> FieldPosition:
    """Kickoff/punt: fixed own yard, or wedge × multiplier."""
    if band.kind == "touchback":
        assert band.touchback_line is not None
        return field_spot_from_own_yard(receiver, band.touchback_line)
    if band.kind == "field":
        assert band.field_yard_from_receiving_goal is not None
        return field_spot_from_own_yard(receiver, band.field_yard_from_receiving_goal)
    if band.kind == "wedge_times":
        assert band.multiplier is not None
        own = min(99, max(1, segment * band.multiplier))
        return field_spot_from_own_yard(receiver, own)
    if band.kind == "wedge_times_penalty":
        assert band.multiplier is not None and band.penalty_yards is not None
        raw = segment * band.multiplier - band.penalty_yards
        own = min(99, max(1, raw))
        return field_spot_from_own_yard(receiver, own)
    raise ValueError(f"unknown spot band kind: {band.kind!r}")


def kickoff_green_bull_recovery_field(kicker: TeamId) -> FieldPosition:
    """Receiving-team fumble; kicking team recovers at opponent's 35-yard line."""
    if kicker is TeamId.RED:
        return field_spot_from_own_yard(kicker, 35)
    return field_spot_from_own_yard(kicker, 65)


def match_spot_band_for_segment(bands: tuple[KickoffBand, ...], segment: int) -> KickoffBand | None:
    for b in bands:
        if segment in b.segments:
            return b
    return None


def match_scrimmage_yard_band(bands: tuple[ScrimmageYardBand, ...], segment: int) -> int | None:
    for b in bands:
        if segment in b.segments:
            return b.yards
    return None


def yards_to_goal_line(field: FieldPosition) -> int:
    return abs(field.goal_yard - field.scrimmage_line)


def advance_field_position(field: FieldPosition, net_toward_goal: int) -> FieldPosition:
    g = field.goal_yard
    s = field.scrimmage_line
    if g == 100:
        ns = s + net_toward_goal
    else:
        ns = s - net_toward_goal
    ns = max(0, min(100, ns))
    return FieldPosition(ns, g)


def is_touchdown_field(field: FieldPosition) -> bool:
    if field.goal_yard == 100:
        return field.scrimmage_line >= 100
    return field.scrimmage_line <= 0


def is_safety_field(field: FieldPosition) -> bool:
    """Offense is down in their own end zone (ball spotted on or past own goal)."""
    if field.goal_yard == 100:
        return field.scrimmage_line <= 0
    return field.scrimmage_line >= 100


def receiver_goal_line_field_position(receiver: TeamId) -> FieldPosition:
    """Receiving team's own goal line (run-out starting point)."""
    if receiver is TeamId.RED:
        return FieldPosition(0, 100)
    return FieldPosition(100, 0)


def defensive_takeover_at_spot(state: GameState, spot: FieldPosition) -> GameState:
    """Previous defense is now on offense at spot.scrimmage_line; goal flips for the new drive."""
    new_off = opponent(state.offense)
    new_goal = 100 if spot.goal_yard == 0 else 0
    nf = FieldPosition(spot.scrimmage_line, new_goal)
    dist = yards_to_goal_line(nf)
    downs = DownAndDistance(1, min(10, dist), nf.scrimmage_line)
    return replace(
        state,
        offense=new_off,
        field=nf,
        downs=downs,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
        declared_fg_attempt=False,
        declared_punt=False,
        safety_pending_kicker=None,
    )


def turnover_on_downs_state(state: GameState, field: FieldPosition) -> GameState:
    return defensive_takeover_at_spot(state, field)
