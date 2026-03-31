"""User-facing football phrasing from internal field state."""

from __future__ import annotations

from dart_football.engine.state import FieldPosition, GameState, TeamId


def team_display_name(team: TeamId) -> str:
    return "Red" if team is TeamId.RED else "Green"


def opponent(team: TeamId) -> TeamId:
    return TeamId.GREEN if team is TeamId.RED else TeamId.RED


def yards_from_own_goal(offense: TeamId, field: FieldPosition) -> int:
    """Yards from the offensive team's own goal line toward the opponent (0–100)."""
    s = field.scrimmage_line
    if field.goal_yard == 100:
        return s
    return 100 - s


def yards_to_opponent_goal_line(offense: TeamId, field: FieldPosition) -> int:
    """Yards remaining to the goal line the offense is driving toward (for TD)."""
    s = field.scrimmage_line
    g = field.goal_yard
    return abs(g - s)


def format_line_of_scrimmage(offense: TeamId, field: FieldPosition) -> str:
    """
    Names the line to match ``field_visual``: Green goal on the left (yard 0),
    Red goal on the right (yard 100). ``scrimmage_line`` is that same 0–100
    axis. The ``offense`` argument is kept for call-site consistency but does
    not change the label (same spot is the same line for both teams).
    """
    p = field.scrimmage_line
    if p == 50:
        return "Midfield (50-yard line)"
    if p < 50:
        return f"Green {p}"
    return f"Red {100 - p}"


def format_distance_to_goal(offense: TeamId, field: FieldPosition) -> str:
    d = yards_to_opponent_goal_line(offense, field)
    return f"{d} yards to goal"


def format_possession_summary(state: GameState) -> str:
    o = state.offense
    f = state.field
    los = format_line_of_scrimmage(o, f)
    dist = format_distance_to_goal(o, f)
    return f"{team_display_name(o)} ball — {los}; {dist}"


def format_down_distance(state: GameState) -> str:
    d = state.downs
    return f"{_ordinal(d.down)} & {d.to_go}"


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 13:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"
