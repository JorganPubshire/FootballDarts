"""Table-driven scrimmage transitions."""

from __future__ import annotations

from dart_football.engine.events import (
    ChoosePatOrTwo,
    ExtraPointOutcome,
    FieldGoalOutcome,
    FourthDownChoice,
    PuntKick,
    ScrimmageDefense,
    ScrimmageOffense,
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
    # PDF: cannot punt on first down
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
    # PDF: FG on 3rd/4th; own 40, 60 yd kick rounded → 60-yard line OK (own 40–49)
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(40, 100),
        downs=DownAndDistance(3, 7, 40),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o = transition(s0, Phase.SCRIMMAGE_OFFENSE, FourthDownChoice(kind="field_goal"), rules)
    assert o.phase == Phase.FIELD_GOAL_ATTEMPT


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


def test_scrimmage_double_ring(rules: RuleSet) -> None:
    s0 = _red_ball_own_25()
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, True, False), rules)
    # PDF segment×1 base (5) × double (2) = 10
    assert o1.state.scrimmage_pending_offense_yards == 10
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(5), rules)
    assert o2.state.field.scrimmage_line == 30


def test_touchdown_then_pat_then_kickoff(rules: RuleSet) -> None:
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(99, 100),
        downs=DownAndDistance(1, 1, 99),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    # PDF segment×1: need net ≥ 1 — e.g. offense 2 vs defense 1
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(2, False, False), rules)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(1), rules)
    assert o2.phase == Phase.PAT_OR_TWO_DECISION
    assert o2.state.scores.red == 6
    assert o2.state.last_touchdown_team == TeamId.RED
    o3 = transition(o2.state, Phase.PAT_OR_TWO_DECISION, ChoosePatOrTwo(extra_point=True), rules)
    assert o3.phase == Phase.EXTRA_POINT_ATTEMPT
    o4 = transition(o3.state, Phase.EXTRA_POINT_ATTEMPT, ExtraPointOutcome(good=True), rules)
    assert o4.phase == Phase.KICKOFF_KICK
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
    assert o1.phase == Phase.FIELD_GOAL_ATTEMPT
    o2 = transition(o1.state, Phase.FIELD_GOAL_ATTEMPT, FieldGoalOutcome(kind="miss"), rules)
    assert o2.phase == Phase.SCRIMMAGE_OFFENSE
    assert o2.state.offense == TeamId.GREEN
    assert o2.state.field.scrimmage_line == 50
    assert o2.state.field.goal_yard == 0


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
    assert o1.phase == Phase.FIELD_GOAL_ATTEMPT
    o2 = transition(o1.state, Phase.FIELD_GOAL_ATTEMPT, FieldGoalOutcome(kind="good"), rules)
    assert o2.phase == Phase.KICKOFF_KICK
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
