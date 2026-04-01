from __future__ import annotations

from dataclasses import replace

from dart_football.display.formatting import opponent
from dart_football.engine.state import DownAndDistance, FieldPosition, GameState, TeamId
from dart_football.engine.transitions.field_geometry import (
    field_spot_from_own_yard,
    kickoff_tee_down_and_distance,
    kickoff_tee_field_position,
)
from dart_football.rules.schema import RuleSet


def state_after_touchdown(state: GameState, scoring: TeamId, rules: RuleSet) -> GameState:
    return replace(
        state,
        scores=state.scores.add(scoring, rules.scoring.touchdown),
        last_touchdown_team=scoring,
        offense=scoring,
        field=FieldPosition(50, 100),
        downs=DownAndDistance(1, 10, 50),
        kickoff_kicker=None,
        kickoff_receiver=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
        declared_fg_attempt=False,
        declared_punt=False,
        fg_snap_field=None,
        fg_pending_outcome="none",
        fg_fake_first_down_line=None,
        safety_pending_kicker=None,
    )


def setup_kickoff_after_score(state: GameState, scoring: TeamId, rules: RuleSet) -> GameState:
    other = opponent(scoring)
    fp = kickoff_tee_field_position(scoring)
    downs = kickoff_tee_down_and_distance(scoring)
    return replace(
        state,
        last_touchdown_team=None,
        kickoff_kicker=scoring,
        kickoff_receiver=other,
        offense=scoring,
        field=fp,
        downs=downs,
        declared_fg_attempt=False,
        declared_punt=False,
        declared_onside=False,
        kickoff_type_selected=False,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        safety_pending_kicker=None,
        fg_snap_field=None,
        fg_pending_outcome="none",
        fg_fake_first_down_line=None,
    )


def safety_free_kick_tee_field(kicker: TeamId, rules: RuleSet) -> FieldPosition:
    y = rules.safety.free_kick_own_yard
    y = max(1, min(99, y))
    return field_spot_from_own_yard(kicker, y)


def setup_safety_free_kick(
    state: GameState, kicker: TeamId, receiver: TeamId, rules: RuleSet
) -> GameState:
    fp = safety_free_kick_tee_field(kicker, rules)
    downs = DownAndDistance(1, 10, fp.scrimmage_line)
    return replace(
        state,
        last_touchdown_team=None,
        kickoff_kicker=kicker,
        kickoff_receiver=receiver,
        offense=kicker,
        field=fp,
        downs=downs,
        declared_fg_attempt=False,
        declared_punt=False,
        declared_onside=False,
        kickoff_type_selected=False,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
        kickoff_awaiting="none",
        kickoff_pending_touchback_line=None,
        fg_snap_field=None,
        fg_pending_outcome="none",
        fg_fake_first_down_line=None,
    )
