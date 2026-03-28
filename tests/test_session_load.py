import json
from pathlib import Path

import pytest

from dart_football.engine.session import GameSession
from dart_football.rules import load_rules_path


def test_load_rules_mismatch_fails(rules_path: Path, tmp_path: Path) -> None:
    p = tmp_path / "sess.json"
    payload = {
        "format": "dart_football_session",
        "format_version": 1,
        "ruleset_id": "wrong-id",
        "ruleset_version": 99,
        "rules_path": str(rules_path),
        "initial_state": {"dummy": True},
        "initial_phase": "pre_game_coin_toss",
        "head": 0,
        "records": [],
        "redo": [],
    }
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="expects ruleset"):
        GameSession.load(p, lambda pth: load_rules_path(Path(pth)), force=False)


def test_load_rules_mismatch_force(rules_path: Path, tmp_path: Path) -> None:
    p = tmp_path / "sess.json"
    payload = {
        "format": "dart_football_session",
        "format_version": 1,
        "ruleset_id": "wrong-id",
        "ruleset_version": 99,
        "rules_path": str(rules_path),
        "initial_state": {
            "scores": {"red": 0, "green": 0},
            "offense": {"__team__": "red"},
            "field": {"scrimmage_line": 50, "goal_yard": 100},
            "downs": {"down": 1, "to_go": 10, "los_yard": 50},
            "clock": {"quarter": 1, "plays_in_quarter": 0, "total_plays": 0},
            "timeouts": {
                "red_q1_q2": 3,
                "red_q3_q4": 3,
                "green_q1_q2": 3,
                "green_q3_q4": 3,
            },
        },
        "initial_phase": "pre_game_coin_toss",
        "head": 0,
        "records": [],
        "redo": [],
    }
    p.write_text(json.dumps(payload), encoding="utf-8")
    sess = GameSession.load(p, lambda pth: load_rules_path(Path(pth)), force=True)
    assert len(sess.load_warnings) == 1
    assert "wrong-id" in sess.load_warnings[0]
