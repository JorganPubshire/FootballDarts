from dataclasses import replace

from dart_football.engine.events import CallTimeout, ChooseKickOrReceive, CoinTossWinner, KickoffKick
from dart_football.engine.phases import Phase
from dart_football.engine.state import GameState, TeamId
from dart_football.engine.transitions import TransitionError, transition
from dart_football.rules.schema import RuleSet


def test_opening_sequence_touchback(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    p0 = Phase.PRE_GAME_COIN_TOSS
    o1 = transition(s0, p0, CoinTossWinner(TeamId.RED), rules)
    assert o1.phase == Phase.CHOOSE_KICK_OR_RECEIVE
    s1 = o1.state
    o2 = transition(s1, Phase.CHOOSE_KICK_OR_RECEIVE, ChooseKickOrReceive(kick=False), rules)
    assert o2.phase == Phase.KICKOFF_KICK
    assert o2.state.kickoff_kicker == TeamId.GREEN
    assert o2.state.kickoff_receiver == TeamId.RED
    assert o2.state.offense == TeamId.GREEN
    assert o2.state.field.scrimmage_line == 65
    assert o2.state.field.goal_yard == 0
    o3 = transition(o2.state, Phase.KICKOFF_KICK, KickoffKick(segment=3), rules)
    assert o3.phase == Phase.SCRIMMAGE_OFFENSE
    assert o3.state.offense == TeamId.RED
    # PDF: segments 1–5 → 1st & 10 at own 40
    assert o3.state.field.scrimmage_line == 40
    assert o3.state.field.goal_yard == 100
    assert o3.state.clock.total_plays == 1


def test_green_receive_touchback_spot(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    s = transition(s0, Phase.PRE_GAME_COIN_TOSS, CoinTossWinner(TeamId.GREEN), rules).state
    s = transition(s, Phase.CHOOSE_KICK_OR_RECEIVE, ChooseKickOrReceive(kick=False), rules).state
    assert s.kickoff_receiver == TeamId.GREEN
    assert s.kickoff_kicker == TeamId.RED
    assert s.offense == TeamId.RED
    assert s.field.scrimmage_line == 35
    assert s.field.goal_yard == 100
    out = transition(s, Phase.KICKOFF_KICK, KickoffKick(segment=1), rules)
    # PDF: own 40 for receiver → GREEN at own 40 → scrimmage 60 toward goal 0
    assert out.state.field.scrimmage_line == 60
    assert out.state.field.goal_yard == 0


def test_kickoff_tee_red_kicker_own_35(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    s = transition(s0, Phase.PRE_GAME_COIN_TOSS, CoinTossWinner(TeamId.RED), rules).state
    s = transition(s, Phase.CHOOSE_KICK_OR_RECEIVE, ChooseKickOrReceive(kick=True), rules).state
    assert s.kickoff_kicker == TeamId.RED
    assert s.offense == TeamId.RED
    assert s.field.scrimmage_line == 35
    assert s.field.goal_yard == 100


def test_call_timeout_does_not_count_play(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    s = transition(s0, Phase.PRE_GAME_COIN_TOSS, CoinTossWinner(TeamId.RED), rules).state
    s = transition(s, Phase.CHOOSE_KICK_OR_RECEIVE, ChooseKickOrReceive(kick=True), rules).state
    assert s.timeouts.red_q1_q2 == 3
    tp0 = s.clock.total_plays
    out = transition(s, Phase.KICKOFF_KICK, CallTimeout(TeamId.RED), rules)
    assert not isinstance(out, TransitionError)
    assert out.state.timeouts.red_q1_q2 == 2
    assert out.state.clock.total_plays == tp0
    assert out.state.clock.plays_in_quarter == s.clock.plays_in_quarter
    assert out.phase == Phase.KICKOFF_KICK


def test_call_timeout_exhausted(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    s = replace(s0, timeouts=replace(s0.timeouts, red_q1_q2=0))
    err = transition(s, Phase.KICKOFF_KICK, CallTimeout(TeamId.RED), rules)
    assert isinstance(err, TransitionError)
