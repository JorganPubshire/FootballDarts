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
    Standard phrasing: own territory as 'Red 35'; opponent territory as
    \"Green's 40-yard line\" from the defense's perspective.
    """
    y = yards_from_own_goal(offense, field)
    name = team_display_name(offense)
    if y < 50:
        return f"{name} {y}"
    if y == 50:
        return "Midfield (50-yard line)"
    opp = opponent(offense)
    opp_name = team_display_name(opp)
    opp_yard = 100 - y
    return f"{opp_name}'s {opp_yard}-yard line"


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
