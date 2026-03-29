from dataclasses import replace

from dart_football.engine.events import (
    CallTimeout,
    ChooseKickoffKind,
    ChooseKickoffTouchbackOrRun,
    ChooseKickOrReceive,
    CoinTossWinner,
    KickoffKick,
    KickoffReturnKick,
    KickoffRunOutKick,
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
    assert not o2.state.kickoff_type_selected
    o2b = transition(o2.state, Phase.KICKOFF_KICK, ChooseKickoffKind(onside=False), rules)
    assert o2b.phase == Phase.KICKOFF_KICK
    assert o2b.state.kickoff_type_selected
    o3 = transition(o2b.state, Phase.KICKOFF_KICK, KickoffKick(segment=3), rules)
    assert o3.phase == Phase.SCRIMMAGE_OFFENSE
    assert o3.state.offense == TeamId.RED
    # segments 1–5 → 1st & 10 at own 40
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
    s2 = transition(s, Phase.KICKOFF_KICK, ChooseKickoffKind(onside=False), rules).state
    out = transition(s2, Phase.KICKOFF_KICK, KickoffKick(segment=1), rules)
    # own 40 for receiver → GREEN at own 40 → scrimmage 60 toward goal 0
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
    assert out.state.skip_next_play_clock_bump


def test_timeout_next_scrimmage_play_does_not_advance_play_counter(rules: RuleSet) -> None:
    s = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(25, 100),
        downs=DownAndDistance(1, 10, 25),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    tp0 = s.clock.total_plays
    out_to = transition(s, Phase.SCRIMMAGE_OFFENSE, CallTimeout(TeamId.RED), rules)
    assert not isinstance(out_to, TransitionError)
    assert out_to.state.skip_next_play_clock_bump
    assert out_to.state.timeouts.red_q1_q2 == 2
    s1 = out_to.state
    o1 = transition(s1, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(3, False, False), rules)
    assert o1.state.clock.total_plays == tp0
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(2), rules)
    assert o2.state.clock.total_plays == tp0
    assert not o2.state.skip_next_play_clock_bump
    o3 = transition(o2.state, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), rules)
    o4 = transition(o3.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(5), rules)
    assert o4.state.clock.total_plays == tp0 + 1


def test_onside_kick_then_same_spot_as_regular(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    s = transition(s0, Phase.PRE_GAME_COIN_TOSS, CoinTossWinner(TeamId.RED), rules).state
    s = transition(s, Phase.CHOOSE_KICK_OR_RECEIVE, ChooseKickOrReceive(kick=True), rules).state
    s = transition(s, Phase.KICKOFF_KICK, ChooseKickoffKind(onside=True), rules).state
    assert s.declared_onside
    out = transition(s, Phase.ONSIDE_KICK, KickoffKick(segment=3), rules)
    assert out.phase == Phase.SCRIMMAGE_OFFENSE
    assert not out.state.declared_onside
    assert out.state.offense.value == "green"


def test_timeout_before_kickoff_skips_kick_play_counter(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    s = transition(s0, Phase.PRE_GAME_COIN_TOSS, CoinTossWinner(TeamId.RED), rules).state
    s = transition(s, Phase.CHOOSE_KICK_OR_RECEIVE, ChooseKickOrReceive(kick=True), rules).state
    s = transition(s, Phase.KICKOFF_KICK, CallTimeout(TeamId.RED), rules).state
    assert s.skip_next_play_clock_bump
    assert s.clock.total_plays == 0
    s = transition(s, Phase.KICKOFF_KICK, ChooseKickoffKind(onside=False), rules).state
    out = transition(s, Phase.KICKOFF_KICK, KickoffKick(segment=10), rules)
    # Segment 9–12: mandatory return dart; play counter advances when return finishes.
    assert out.phase == Phase.KICKOFF_RETURN_DART
    assert out.state.clock.total_plays == 0
    assert out.state.skip_next_play_clock_bump
    s2 = out.state
    out2 = transition(s2, Phase.KICKOFF_RETURN_DART, KickoffReturnKick(segment=5), rules)
    assert out2.state.clock.total_plays == 0
    assert not out2.state.skip_next_play_clock_bump


def test_call_timeout_exhausted(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    s = replace(s0, timeouts=replace(s0.timeouts, red_q1_q2=0))
    err = transition(s, Phase.KICKOFF_KICK, CallTimeout(TeamId.RED), rules)
    assert isinstance(err, TransitionError)


def test_kickoff_segment_13_touchback_at_35(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    s = transition(s0, Phase.PRE_GAME_COIN_TOSS, CoinTossWinner(TeamId.RED), rules).state
    s = transition(s, Phase.CHOOSE_KICK_OR_RECEIVE, ChooseKickOrReceive(kick=False), rules).state
    assert s.kickoff_receiver == TeamId.RED
    s = transition(s, Phase.KICKOFF_KICK, ChooseKickoffKind(onside=False), rules).state
    o = transition(s, Phase.KICKOFF_KICK, KickoffKick(segment=13), rules)
    assert o.phase == Phase.KICKOFF_RUN_OR_SPOT
    assert o.state.kickoff_pending_touchback_line == 35
    o2 = transition(o.state, Phase.KICKOFF_RUN_OR_SPOT, ChooseKickoffTouchbackOrRun(take_touchback=True), rules)
    assert o2.phase == Phase.SCRIMMAGE_OFFENSE
    assert o2.state.offense == TeamId.RED
    assert o2.state.field.scrimmage_line == 35
    assert o2.state.field.goal_yard == 100


def test_kickoff_segment_13_run_out_wedge_5(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    s = transition(s0, Phase.PRE_GAME_COIN_TOSS, CoinTossWinner(TeamId.RED), rules).state
    s = transition(s, Phase.CHOOSE_KICK_OR_RECEIVE, ChooseKickOrReceive(kick=False), rules).state
    s = transition(s, Phase.KICKOFF_KICK, ChooseKickoffKind(onside=False), rules).state
    o = transition(s, Phase.KICKOFF_KICK, KickoffKick(segment=13), rules)
    o2 = transition(o.state, Phase.KICKOFF_RUN_OR_SPOT, ChooseKickoffTouchbackOrRun(take_touchback=False), rules)
    assert o2.phase == Phase.KICKOFF_RUN_OUT_DART
    assert o2.state.field.scrimmage_line == 0
    o3 = transition(o2.state, Phase.KICKOFF_RUN_OUT_DART, KickoffRunOutKick(segment=5), rules)
    assert o3.phase == Phase.SCRIMMAGE_OFFENSE
    assert o3.state.field.scrimmage_line == 25


def test_kickoff_segment_10_then_return(rules: RuleSet) -> None:
    s0 = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    s = transition(s0, Phase.PRE_GAME_COIN_TOSS, CoinTossWinner(TeamId.RED), rules).state
    s = transition(s, Phase.CHOOSE_KICK_OR_RECEIVE, ChooseKickOrReceive(kick=False), rules).state
    s = transition(s, Phase.KICKOFF_KICK, ChooseKickoffKind(onside=False), rules).state
    o = transition(s, Phase.KICKOFF_KICK, KickoffKick(segment=10), rules)
    assert o.phase == Phase.KICKOFF_RETURN_DART
    assert o.state.field.scrimmage_line == 50
    o2 = transition(o.state, Phase.KICKOFF_RETURN_DART, KickoffReturnKick(segment=4), rules)
    assert o2.phase == Phase.SCRIMMAGE_OFFENSE
    assert o2.state.field.scrimmage_line == 62


def test_plays_per_quarter_advances_quarter(rules: RuleSet) -> None:
    r2 = replace(rules, structure=replace(rules.structure, plays_per_quarter=2))
    s = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(25, 100),
        downs=DownAndDistance(1, 10, 25),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    o1 = transition(s, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(5, False, False), r2)
    o2 = transition(o1.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(5), r2)
    assert o2.state.clock.quarter == 1
    assert o2.state.clock.plays_in_quarter == 1
    o3 = transition(o2.state, Phase.SCRIMMAGE_OFFENSE, ScrimmageOffense(4, False, False), r2)
    o4 = transition(o3.state, Phase.SCRIMMAGE_DEFENSE, ScrimmageDefense(4), r2)
    assert o4.state.clock.quarter == 2
    assert o4.state.clock.plays_in_quarter == 0
    assert o4.state.clock.total_plays == 2
