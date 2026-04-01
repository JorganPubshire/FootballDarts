"""Safety detection from scrimmage and regulation / overtime phase hooks."""

from __future__ import annotations

from dataclasses import replace

from dart_football.engine.events import (
    CoinTossWinner,
    ConfirmSafetyKickoff,
    ExtraPointOutcome,
    ScrimmageDefense,
    ScrimmageOffense,
)
from dart_football.engine.phases import Phase
from dart_football.engine.state import (
    DownAndDistance,
    FieldPosition,
    GameClock,
    GameState,
    Scoreboard,
    TeamId,
    Timeouts,
)
from dart_football.engine.transitions import transition
from dart_football.rules.schema import RuleSet


def test_safety_when_offense_driven_into_own_end_zone(rules: RuleSet) -> None:
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(3, 100),
        downs=DownAndDistance(1, 10, 3),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(1, False, False), rules)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(20), rules)
    assert o2.phase == Phase.SAFETY_SEQUENCE
    assert o2.state.scores.green == rules.scoring.safety
    assert o2.state.safety_pending_kicker is TeamId.RED


def test_safety_confirm_sets_up_free_kick(rules: RuleSet) -> None:
    s0 = GameState(
        scores=Scoreboard(red=0, green=2),
        offense=TeamId.RED,
        field=FieldPosition(0, 100),
        downs=DownAndDistance(1, 10, 0),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
        safety_pending_kicker=TeamId.RED,
    )
    o = transition(s0, Phase.SAFETY_SEQUENCE, ConfirmSafetyKickoff(), rules)
    assert o.phase == Phase.KICKOFF_KICK
    assert o.state.kickoff_kicker is TeamId.RED
    assert o.state.kickoff_receiver is TeamId.GREEN
    assert o.state.field.scrimmage_line == 20
    assert o.state.field.goal_yard == 100


def test_regulation_tie_with_overtime_enabled(rules: RuleSet) -> None:
    r_ot = replace(
        rules,
        structure=replace(rules.structure, quarters=4, plays_per_quarter=1),
        overtime=replace(rules.overtime, enabled=True),
    )
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(25, 100),
        downs=DownAndDistance(1, 10, 25),
        clock=GameClock(4, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), r_ot)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(5), r_ot)
    assert o2.state.clock.quarter == 5
    assert o2.state.overtime_period == 1
    assert o2.phase == Phase.OVERTIME_START
    assert o2.state.coin_toss_winner is None


def test_regulation_tie_without_overtime_is_final(rules: RuleSet) -> None:
    r = replace(
        rules,
        structure=replace(rules.structure, quarters=4, plays_per_quarter=1),
        overtime=replace(rules.overtime, enabled=False),
    )
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(30, 100),
        downs=DownAndDistance(1, 10, 30),
        clock=GameClock(4, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), r)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(5), r)
    assert o2.phase == Phase.GAME_OVER


def test_regulation_leader_skips_overtime(rules: RuleSet) -> None:
    r_ot = replace(
        rules,
        structure=replace(rules.structure, quarters=4, plays_per_quarter=1),
        overtime=replace(rules.overtime, enabled=True),
    )
    s0 = GameState(
        scores=Scoreboard(red=3, green=0),
        offense=TeamId.RED,
        field=FieldPosition(40, 100),
        downs=DownAndDistance(1, 10, 40),
        clock=GameClock(4, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s0, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), r_ot)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(5), r_ot)
    assert o2.phase == Phase.GAME_OVER


def test_overtime_coin_toss(rules: RuleSet) -> None:
    s0 = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(50, 100),
        downs=DownAndDistance(1, 10, 50),
        clock=GameClock(5, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
        overtime_period=1,
    )
    o = transition(s0, Phase.OVERTIME_START, CoinTossWinner(TeamId.GREEN), rules)
    assert o.phase == Phase.CHOOSE_KICK_OR_RECEIVE
    assert o.state.coin_toss_winner is TeamId.GREEN


def test_first_score_template_ends_game_at_kickoff_phase(rules: RuleSet) -> None:
    r_fs = replace(
        rules,
        overtime=replace(rules.overtime, enabled=True, template="first_score"),
    )
    s0 = GameState(
        scores=Scoreboard(red=6, green=0),
        offense=TeamId.RED,
        field=FieldPosition(50, 100),
        downs=DownAndDistance(1, 10, 50),
        clock=GameClock(5, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
        last_touchdown_team=TeamId.RED,
        overtime_period=1,
    )
    o = transition(s0, Phase.EXTRA_POINT_ATTEMPT, ExtraPointOutcome(good=False), r_fs)
    assert o.phase == Phase.GAME_OVER
