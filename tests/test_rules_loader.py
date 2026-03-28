from pathlib import Path

from dart_football.rules import load_rules_path


def test_load_standard(rules_path: Path) -> None:
    r = load_rules_path(rules_path)
    assert r.ruleset_version == 1
    assert r.ruleset_id == "standard"
    assert r.structure.timeouts_per_half == 3
    assert len(r.kickoff.bands) >= 1
    assert r.scrimmage.max_loss_yards == 10
    assert len(r.scrimmage.offense_yards) >= 1
    assert "kickoff" in r.throw_markers.kickoff_line.lower()
    assert "offense" in r.throw_markers.offense_line.lower()
    assert "defense" in r.throw_markers.defense_line.lower()
