"""Table-driven scrimmage transitions."""

from __future__ import annotations

from dart_football.engine.events import (
    ChooseExtraPointOrTwo,
    ExtraPointOutcome,
    FieldGoalDefenseDart,
    FieldGoalOffenseDart,
    FieldGoalOutcome,
    FourthDownChoice,
    PuntKick,
    ScrimmageDefense,
    ScrimmageOffense,
    ScrimmageStripDart,
)
from dart_football.engine.phases import Phase
from dart_football.engine.state import DownAndDistance, FieldPosition, GameClock, GameState, Scoreboard, TeamId, Timeouts
from dart_football.engine.transitions import TransitionError, transition
from dart_football.rules.schema import RuleSet


def _red_ball_own_25() -> GameState:
    return GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(25, 100),
        downs=DownAndDistance(1, 10, 25),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )


def test_scrimmage_declare_punt_from_offense(rules: RuleSet) -> None:
    # cannot punt on first down
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(25, 100),
        downs=DownAndDistance(2, 10, 25),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o = transition(s0, Phase.SCRIMMAGE_OFFENSE, FourthDownChoice(kind="punt"), rules)
    assert o.phase == Phase.PUNT_ATTEMPT


def test_scrimmage_declare_fg_in_range(rules: RuleSet) -> None:
    # FG on 3rd/4th; own 40, 60 yd kick rounded → 60-yard line OK (own 40–49)
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(40, 100),
        downs=DownAndDistance(3, 7, 40),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o = transition(s0, Phase.SCRIMMAGE_OFFENSE, FourthDownChoice(kind="field_goal"), rules)
    assert o.phase == Phase.FIELD_GOAL_OFFENSE_DART


def test_scrimmage_declare_fg_out_of_range(rules: RuleSet) -> None:
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(25, 100),
        downs=DownAndDistance(3, 10, 25),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o = transition(s0, Phase.SCRIMMAGE_OFFENSE, FourthDownChoice(kind="field_goal"), rules)
    assert isinstance(o, TransitionError)


def test_punt_not_on_first_down(rules: RuleSet) -> None:
    o = transition(_red_ball_own_25(), Phase.SCRIMMAGE_OFFENSE, FourthDownChoice(kind="punt"), rules)
    assert isinstance(o, TransitionError)


def test_fg_not_on_first_or_second_down(rules: RuleSet) -> None:
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(40, 100),
        downs=DownAndDistance(2, 7, 40),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o = transition(s0, Phase.SCRIMMAGE_OFFENSE, FourthDownChoice(kind="field_goal"), rules)
    assert isinstance(o, TransitionError)


def test_scrimmage_offense_then_defense_advances(rules: RuleSet) -> None:
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), rules)
    assert o1.phase == Phase.SCRIMMAGE_DEFENSE
    assert o1.state.scrimmage_pending_offense_yards == 5
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(5), rules)
    assert o2.phase == Phase.SCRIMMAGE_OFFENSE
    assert o2.state.field.scrimmage_line == 25
    assert o2.state.downs.down == 2
    assert o2.state.scrimmage_pending_offense_yards is None


def test_offense_green_bull_counts_as_green_wedge_yards(rules: RuleSet) -> None:
    bg = rules.scrimmage.bull_green_segment
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(segment=bg, bull="green"), rules)
    assert o1.phase == Phase.SCRIMMAGE_DEFENSE
    assert o1.state.scrimmage_pending_offense_yards == bg
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(10), rules)
    assert o2.state.offense == TeamId.RED
    assert o2.state.field.scrimmage_line == 25
    assert o2.state.downs.down == 2


def test_offense_green_bull_defense_red_turnover_at_los(rules: RuleSet) -> None:
    bg = rules.scrimmage.bull_green_segment
    br = rules.scrimmage.bull_red_segment
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(segment=bg, bull="green"), rules)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(segment=br, bull="red"), rules)
    assert o2.phase == Phase.SCRIMMAGE_OFFENSE
    assert o2.state.offense == TeamId.GREEN
    assert o2.state.field.scrimmage_line == 25
    assert o2.state.field.goal_yard == 0
    assert o2.state.scores.red == o2.state.scores.green == 0


def test_offense_red_bull_then_defense_no_effect_advances_down(rules: RuleSet) -> None:
    br = rules.scrimmage.bull_red_segment
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(segment=br, bull="red"), rules)
    assert o1.phase == Phase.SCRIMMAGE_DEFENSE
    assert o1.state.scrimmage_pending_offense_yards == 0
    assert o1.state.scrimmage_pending_offense_kind == "red"
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(10), rules)
    assert o2.state.offense == TeamId.RED
    assert o2.state.field.scrimmage_line == 25
    assert o2.state.downs.down == 2


def test_offense_red_bull_defense_red_no_gain_at_los(rules: RuleSet) -> None:
    br = rules.scrimmage.bull_red_segment
    bg = rules.scrimmage.bull_green_segment
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(segment=br, bull="red"), rules)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(segment=bg, bull="red"), rules)
    assert o2.state.offense == TeamId.RED
    assert o2.state.field.scrimmage_line == 25
    assert o2.state.downs.down == 2


def test_defense_green_bull_goes_to_strip_dart(rules: RuleSet) -> None:
    bg = rules.scrimmage.bull_green_segment
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), rules)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(segment=bg, bull="green"), rules)
    assert o2.phase == Phase.SCRIMMAGE_STRIP_DART
    assert o2.state.scrimmage_pending_offense_yards == 5
    assert o2.state.scrimmage_pending_offense_eff_segment == 5


def test_strip_dart_matching_color_yards_then_turnover(rules: RuleSet) -> None:
    """Offense wedge 5 and strip wedge 1 share board-color parity in standard wire order."""
    bg = rules.scrimmage.bull_green_segment
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), rules)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(segment=bg, bull="green"), rules)
    o3 = transition(o2.state, Phase.SCRIMMAGE_STRIP_DART, ScrimmageStripDart(segment=1), rules)
    assert o3.phase == Phase.SCRIMMAGE_OFFENSE
    assert o3.state.offense == TeamId.GREEN
    assert o3.state.field.scrimmage_line == 30
    assert o3.state.field.goal_yard == 0


def test_strip_dart_mismatch_turnover_at_los(rules: RuleSet) -> None:
    bg = rules.scrimmage.bull_green_segment
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), rules)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(segment=bg, bull="green"), rules)
    o3 = transition(o2.state, Phase.SCRIMMAGE_STRIP_DART, ScrimmageStripDart(segment=20), rules)
    assert o3.phase == Phase.SCRIMMAGE_OFFENSE
    assert o3.state.offense == TeamId.GREEN
    assert o3.state.field.scrimmage_line == 25
    assert o3.state.field.goal_yard == 0


def test_defense_red_bull_defensive_touchdown(rules: RuleSet) -> None:
    br = rules.scrimmage.bull_red_segment
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), rules)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(segment=br, bull="red"), rules)
    assert o2.phase == Phase.AFTER_TOUCHDOWN_CHOICE
    assert o2.state.scores.green == 6


def test_defense_red_bull_near_goal_defensive_td_not_offense_td(rules: RuleSet) -> None:
    br = rules.scrimmage.bull_red_segment
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(96, 100),
        downs=DownAndDistance(1, 4, 96),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), rules)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(segment=br, bull="red"), rules)
    assert o2.phase == Phase.AFTER_TOUCHDOWN_CHOICE
    assert o2.state.scores.green == 6
    assert o2.state.scores.red == 0


def test_turnover_on_downs_after_fourth_down_no_first_down(rules: RuleSet) -> None:
    """Standard scrimmage: 4th down with no new first down flips possession at the new LOS."""
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(25, 100),
        downs=DownAndDistance(4, 10, 25),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    # Offense 4 yd vs defense 4 yd → net 0; down advances past 4 → turnover on downs
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(4, False, False), rules)
    assert o1.phase == Phase.SCRIMMAGE_DEFENSE
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(4), rules)
    assert not isinstance(o2, TransitionError)
    assert o2.phase == Phase.SCRIMMAGE_OFFENSE
    assert o2.state.offense == TeamId.GREEN
    assert o2.state.field.scrimmage_line == 25
    assert o2.state.field.goal_yard == 0
    assert o2.state.downs.down == 1
    assert o2.state.downs.to_go == 10
    assert "turnover on downs" in o2.effects_summary.lower()


def test_scrimmage_double_ring(rules: RuleSet) -> None:
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, True, False), rules)
    # segment×1 base (5) × double (2) = 10
    assert o1.state.scrimmage_pending_offense_yards == 10
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(5), rules)
    assert o2.state.field.scrimmage_line == 30


def test_touchdown_then_extra_point_then_kickoff(rules: RuleSet) -> None:
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(99, 100),
        downs=DownAndDistance(1, 1, 99),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    # segment×1: need net ≥ 1 — e.g. offense 2 vs defense 1
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(2, False, False), rules)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(1), rules)
    assert o2.phase == Phase.AFTER_TOUCHDOWN_CHOICE
    assert o2.state.scores.red == 6
    assert o2.state.last_touchdown_team == TeamId.RED
    o3 = transition(o2.state, Phase.AFTER_TOUCHDOWN_CHOICE, ChooseExtraPointOrTwo(extra_point=True), rules)
    assert o3.phase == Phase.EXTRA_POINT_ATTEMPT
    o4 = transition(o3.state, Phase.EXTRA_POINT_ATTEMPT, ExtraPointOutcome(good=True), rules)
    assert o4.phase == Phase.KICKOFF_KICK
    assert not o4.state.kickoff_type_selected
    assert o4.state.scores.red == 7
    assert o4.state.kickoff_kicker == TeamId.RED
    assert o4.state.kickoff_receiver == TeamId.GREEN
    assert o4.state.offense == TeamId.RED
    assert o4.state.field.scrimmage_line == 35
    assert o4.state.field.goal_yard == 100


def test_field_goal_miss_opponent_plus_ten(rules: RuleSet) -> None:
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(40, 100),
        downs=DownAndDistance(4, 7, 40),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s0, Phase.FOURTH_DOWN_DECISION, FourthDownChoice(kind="field_goal"), rules)
    assert o1.phase == Phase.FIELD_GOAL_OFFENSE_DART
    o_mid = transition(
        o1.state,
        Phase.FIELD_GOAL_OFFENSE_DART,
        FieldGoalOffenseDart(zone="outside_triples", segment=5),
        rules,
    )
    assert o_mid.phase == Phase.FIELD_GOAL_DEFENSE
    o2 = transition(
        o_mid.state,
        Phase.FIELD_GOAL_DEFENSE,
        FieldGoalDefenseDart(segment=10, bull="none"),
        rules,
    )
    assert o2.phase == Phase.SCRIMMAGE_OFFENSE
    assert o2.state.offense == TeamId.GREEN
    assert o2.state.field.scrimmage_line == 50
    assert o2.state.field.goal_yard == 0


def test_legacy_field_goal_outcome_still_works_on_offense_dart_phase(rules: RuleSet) -> None:
    """Saved sessions may record FieldGoalOutcome before the dart-based FG flow."""
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(85, 100),
        downs=DownAndDistance(4, 5, 85),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
        declared_fg_attempt=True,
        fg_snap_field=FieldPosition(85, 100),
    )
    o = transition(s0, Phase.FIELD_GOAL_OFFENSE_DART, FieldGoalOutcome(kind="good"), rules)
    assert o.phase == Phase.KICKOFF_KICK
    assert o.state.scores.red == 3


def test_fourth_down_field_goal_then_kickoff(rules: RuleSet) -> None:
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(85, 100),
        downs=DownAndDistance(4, 5, 85),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s0, Phase.FOURTH_DOWN_DECISION, FourthDownChoice(kind="field_goal"), rules)
    assert o1.phase == Phase.FIELD_GOAL_OFFENSE_DART
    o_mid = transition(
        o1.state,
        Phase.FIELD_GOAL_OFFENSE_DART,
        FieldGoalOffenseDart(zone="inner_triple", segment=5),
        rules,
    )
    assert o_mid.phase == Phase.FIELD_GOAL_DEFENSE
    o2 = transition(
        o_mid.state,
        Phase.FIELD_GOAL_DEFENSE,
        FieldGoalDefenseDart(segment=10, bull="none"),
        rules,
    )
    assert o2.phase == Phase.KICKOFF_KICK
    assert not o2.state.kickoff_type_selected
    assert o2.state.scores.red == 3
    assert o2.state.offense == TeamId.RED
    assert o2.state.field.scrimmage_line == 35
    assert o2.state.field.goal_yard == 100


def test_fourth_down_punt(rules: RuleSet) -> None:
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(40, 100),
        downs=DownAndDistance(4, 8, 40),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s0, Phase.FOURTH_DOWN_DECISION, FourthDownChoice(kind="punt"), rules)
    assert o1.phase == Phase.PUNT_ATTEMPT
    o2 = transition(o1.state, Phase.PUNT_ATTEMPT, PuntKick(segment=5), rules)
    assert o2.phase == Phase.SCRIMMAGE_OFFENSE
    assert o2.state.offense == TeamId.GREEN


def test_punt_fake_green_no_gain_advances_down(rules: RuleSet) -> None:
    bg = rules.scrimmage.bull_green_segment
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(33, 100),
        downs=DownAndDistance(2, 7, 33),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, FourthDownChoice(kind="punt"), rules)
    o2 = transition(o1.state, Phase.PUNT_ATTEMPT, PuntKick(segment=bg, bull="green"), rules)
    assert o2.state.offense == TeamId.RED
    assert o2.state.field.scrimmage_line == 33
    assert o2.state.downs.down == 3
    assert o2.state.downs.to_go == 7


def test_punt_blocked_red_turnover_at_los(rules: RuleSet) -> None:
    br = rules.scrimmage.bull_red_segment
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(40, 100),
        downs=DownAndDistance(4, 8, 40),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s0, Phase.FOURTH_DOWN_DECISION, FourthDownChoice(kind="punt"), rules)
    o2 = transition(o1.state, Phase.PUNT_ATTEMPT, PuntKick(segment=br, bull="red"), rules)
    assert o2.phase == Phase.SCRIMMAGE_OFFENSE
    assert o2.state.offense == TeamId.GREEN
    assert o2.state.field.scrimmage_line == 40
    assert o2.state.field.goal_yard == 0
