import json
from pathlib import Path

from dart_football.engine.events import ChooseKickoffKind, ChooseKickOrReceive, CoinTossWinner, KickoffKick
from dart_football.engine.phases import Phase
from dart_football.engine.session import GameSession
from dart_football.engine.state import GameState, TeamId
from dart_football.engine.transitions import TransitionOk
from dart_football.rules import load_rules_path


def test_undo_redo(rules, rules_path: Path) -> None:
    initial = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    sess = GameSession.new(initial, Phase.PRE_GAME_COIN_TOSS, rules, str(rules_path))
    assert sess.apply(CoinTossWinner(TeamId.RED))
    assert sess.apply(ChooseKickOrReceive(kick=True))
    s_mid, ph = sess.current_state_phase()
    assert ph == Phase.KICKOFF_KICK
    assert sess.undo()
    _, ph2 = sess.current_state_phase()
    assert ph2 == Phase.CHOOSE_KICK_OR_RECEIVE
    assert sess.redo()
    s2, ph3 = sess.current_state_phase()
    assert ph3 == Phase.KICKOFF_KICK
    assert s2.kickoff_kicker == TeamId.RED


def test_correct_kickoff(rules, rules_path: Path, tmp_path: Path) -> None:
    initial = GameState.new_game(timeouts_per_half=rules.structure.timeouts_per_half)
    sess = GameSession.new(initial, Phase.PRE_GAME_COIN_TOSS, rules, str(rules_path))
    sess.apply(CoinTossWinner(TeamId.RED))
    sess.apply(ChooseKickOrReceive(kick=False))
    sess.apply(ChooseKickoffKind(onside=False))
    sess.apply(KickoffKick(segment=20))
    line_wrong = sess.current_state_phase()[0].field.scrimmage_line
    out = sess.correct(KickoffKick(segment=3))
    assert isinstance(out, TransitionOk)
    line_right = sess.current_state_phase()[0].field.scrimmage_line
    assert line_wrong != line_right
    # kickoff: segments 1–5 → receiving team ball at own 40
    assert line_right == 40
    assert sess.records[-1].supersedes_seq == 4

    p = tmp_path / "s.json"
    sess.save(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["head"] == 4
    assert data.get("large_field") is False
    loaded = GameSession.load(p, lambda pth: load_rules_path(Path(pth)))
    assert loaded.large_field is False
    assert loaded.head == 4
    assert loaded.current_state_phase()[0].field.scrimmage_line == 40
