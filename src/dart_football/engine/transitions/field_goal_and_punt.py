from __future__ import annotations

from dataclasses import replace

from dart_football.display.formatting import opponent, yards_from_own_goal
from dart_football.engine.events import FieldGoalFakeOffenseDart
from dart_football.engine.state import DownAndDistance, FieldPosition, GameState, TeamId
from dart_football.engine.transitions.field_geometry import yards_to_goal_line
from dart_football.engine.transitions.scrimmage_resolution import effective_segment_with_bull
from dart_football.engine.transitions.types import TransitionError
from dart_football.rules.schema import RuleSet


def round_up_to_ten(yards: int) -> int:
    return ((yards + 9) // 10) * 10


def sixty_yard_field_goal_line_ok(state: GameState) -> bool:
    """60-yard field goals only from own 40 to 49."""
    dist = yards_to_goal_line(state.field)
    if round_up_to_ten(dist) != 60:
        return True
    own = yards_from_own_goal(state.offense, state.field)
    return 40 <= own <= 49


def field_after_missed_field_goal(state: GameState, rules: RuleSet) -> GameState:
    """Missed/blocked FG — opponent takes over at previous line of scrimmage +10 yards."""
    opp = opponent(state.offense)
    fp = state.field
    s, g = fp.scrimmage_line, fp.goal_yard
    dy = rules.field_goal.miss_spot_offset_yards
    if g == 100:
        new_line = min(99, s + dy)
    else:
        new_line = max(1, s - dy)
    new_goal = 100 if opp is TeamId.RED else 0
    nf = FieldPosition(new_line, new_goal)
    dist = yards_to_goal_line(nf)
    downs = DownAndDistance(1, min(10, dist), new_line)
    return replace(
        state,
        offense=opp,
        field=nf,
        downs=downs,
        declared_fg_attempt=False,
        declared_punt=False,
        scrimmage_pending_offense_yards=None,
        scrimmage_pending_offense_kind="none",
        scrimmage_pending_offense_eff_segment=None,
        fg_snap_field=None,
        fg_pending_outcome="none",
        fg_fake_first_down_line=None,
        safety_pending_kicker=None,
    )


def field_goal_sequence_clear_fields() -> dict:
    return {
        "fg_snap_field": None,
        "fg_pending_outcome": "none",
        "fg_fake_first_down_line": None,
        "declared_fg_attempt": False,
        "safety_pending_kicker": None,
    }


def team_field_goal_board_parity(team: TeamId) -> int:
    return 0 if team is TeamId.RED else 1


def first_down_line_yard(field: FieldPosition, downs: DownAndDistance) -> int:
    s, g = field.scrimmage_line, field.goal_yard
    t = downs.to_go
    if g == 100:
        return min(100, s + t)
    return max(0, s - t)


def fake_field_goal_defense_green_field(
    field: FieldPosition, first_down_line: int
) -> FieldPosition:
    g = field.goal_yard
    if g == 100:
        one_short = max(0, first_down_line - 1)
        own_eleven = 11
        s_new = min(one_short, own_eleven)
    else:
        one_short = min(100, first_down_line + 1)
        own_eleven = 89
        s_new = max(one_short, own_eleven)
    return FieldPosition(s_new, g)


def field_goal_fake_yards_from_dart(event: FieldGoalFakeOffenseDart, rules: RuleSet) -> int | None:
    sc = rules.scrimmage
    eff = (
        event.segment
        if event.bull == "none"
        else effective_segment_with_bull(event.segment, event.bull, rules)
    )
    if eff < sc.segment_min or eff > sc.segment_max:
        return None
    if not sc.use_wedge_number_yards:
        return None
    if event.bull == "red":
        return 0
    if event.bull == "green":
        return eff
    mult = 1
    if event.triple_ring:
        mult *= sc.triple_multiplier
    if event.double_ring:
        mult *= sc.double_multiplier
    return eff * mult


def fg_kick_range_error_or_none(st: GameState, rules: RuleSet) -> TransitionError | None:
    dist = yards_to_goal_line(st.field)
    if dist > rules.field_goal.max_distance_yards:
        return TransitionError(
            f"FG distance {dist} yd exceeds max {rules.field_goal.max_distance_yards}",
            ("FieldGoalOffenseDart", "ChooseFieldGoalAfterGreen"),
        )
    if not sixty_yard_field_goal_line_ok(st):
        return TransitionError(
            "60-yard field goals only from your own 40 to 49 yard line",
            ("FieldGoalOffenseDart", "ChooseFieldGoalAfterGreen"),
        )
    return None
