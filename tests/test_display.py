"""Table-driven tests for football phrasing."""

from __future__ import annotations

import pytest

from dart_football.display import (
    format_distance_to_goal,
    format_line_of_scrimmage,
    yards_from_own_goal,
    yards_to_opponent_goal_line,
)
from dart_football.display.field_visual import first_down_line_yard, format_field_visual
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


@pytest.mark.parametrize(
    ("offense", "scrimmage_line", "goal_yard", "expected_own_yards"),
    [
        (TeamId.RED, 25, 100, 25),
        (TeamId.RED, 75, 100, 75),
        (TeamId.GREEN, 75, 0, 25),
        (TeamId.GREEN, 25, 0, 75),
    ],
)
def test_yards_from_own_goal(
    offense: TeamId,
    scrimmage_line: int,
    goal_yard: int,
    expected_own_yards: int,
) -> None:
    f = FieldPosition(scrimmage_line, goal_yard)
    assert yards_from_own_goal(offense, f) == expected_own_yards


@pytest.mark.parametrize(
    ("offense", "scrimmage_line", "goal_yard", "expected_to_goal"),
    [
        (TeamId.RED, 25, 100, 75),
        (TeamId.RED, 75, 100, 25),
        (TeamId.GREEN, 75, 0, 75),
    ],
)
def test_yards_to_goal(
    offense: TeamId,
    scrimmage_line: int,
    goal_yard: int,
    expected_to_goal: int,
) -> None:
    f = FieldPosition(scrimmage_line, goal_yard)
    assert yards_to_opponent_goal_line(offense, f) == expected_to_goal


@pytest.mark.parametrize(
    ("offense", "scrimmage_line", "goal_yard", "substr"),
    [
        (TeamId.RED, 35, 100, "Red 35"),
        (TeamId.RED, 75, 100, "Green's 25-yard line"),
        (TeamId.GREEN, 75, 0, "Green 25"),
    ],
)
def test_format_line_of_scrimmage_contains(
    offense: TeamId,
    scrimmage_line: int,
    goal_yard: int,
    substr: str,
) -> None:
    f = FieldPosition(scrimmage_line, goal_yard)
    s = format_line_of_scrimmage(offense, f)
    assert substr in s


def test_midfield() -> None:
    f = FieldPosition(50, 100)
    assert "Midfield" in format_line_of_scrimmage(TeamId.RED, f)
    assert "50" in format_distance_to_goal(TeamId.RED, f)


def test_first_down_line_yard() -> None:
    f = FieldPosition(40, 100)
    d = DownAndDistance(2, 10, 40)
    assert first_down_line_yard(f, d) == 50
    f2 = FieldPosition(60, 0)
    d2 = DownAndDistance(1, 10, 60)
    assert first_down_line_yard(f2, d2) == 50


def test_format_field_visual_contains_markers() -> None:
    s = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(35, 100),
        downs=DownAndDistance(1, 10, 35),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    out = format_field_visual(s).plain
    assert "●" in out or "◆" in out
    assert "LOS 35" in out
    assert "1st-down line 45" in out


def test_format_field_visual_kickoff_omits_first_down() -> None:
    """Kickoff is not a scrimmage — no 1st-down marker or down & distance on the diagram."""
    s = GameState(
        scores=Scoreboard(),
        offense=TeamId.RED,
        field=FieldPosition(35, 100),
        downs=DownAndDistance(1, 10, 35),
        clock=GameClock(1, 0, 0),
        timeouts=Timeouts(3, 3, 3, 3),
    )
    out = format_field_visual(s, phase=Phase.KICKOFF_KICK).plain
    assert "1st-down" not in out
    assert "& 10" not in out
    assert "Kickoff spot" in out
    assert "●" in out
