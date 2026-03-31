from pathlib import Path

from dart_football.rules import load_rules_path


def test_load_standard(rules_path: Path) -> None:
    r = load_rules_path(rules_path)
    assert r.ruleset_version == 1
    assert r.ruleset_id == "standard"
    assert r.structure.timeouts_per_half == 3
    assert r.structure.plays_per_quarter == 24
    assert len(r.kickoff.bands) >= 1
    assert r.scrimmage.max_loss_yards == 10
    assert len(r.scrimmage.offense_yards) >= 1
    assert "oldest" in r.throw_markers.coin_toss_dart_line.lower()
    assert "kickoff" in r.throw_markers.kickoff_line.lower()
    assert "20-yard" in r.throw_markers.offense_line.lower()
    assert "30-yard" in r.throw_markers.defense_line.lower()
    assert r.safety.free_kick_own_yard == 20
