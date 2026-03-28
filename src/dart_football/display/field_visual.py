"""ASCII field diagram: endzones, yard markers, LOS, first-down line."""

from __future__ import annotations

from rich.text import Text

from dart_football.engine.phases import Phase
from dart_football.engine.state import DownAndDistance, FieldPosition, GameState

# Horizontal resolution (0–100 yards maps to 0 .. WIDTH-1)
_WIDTH = 51
_EZ = 3  # columns at each end representing the end zone on the diagram


def first_down_line_yard(field: FieldPosition, downs: DownAndDistance) -> int:
    """Yard line (0–100) where a first down is earned."""
    s = field.scrimmage_line
    g = field.goal_yard
    t = downs.to_go
    if g == 100:
        return min(100, s + t)
    return max(0, s - t)


def _yard_to_col(yard: int) -> int:
    return max(0, min(_WIDTH - 1, round(yard * (_WIDTH - 1) / 100)))


def _grass_char_style(col: int, ch: str) -> str:
    """Color: Green's end zone left (0), Red's end zone right (100); markers in between."""
    in_green_ez = col < _EZ
    in_red_ez = col >= _WIDTH - _EZ
    if in_green_ez:
        if ch in ("●", "◆", "▼"):
            return "bold yellow on green"
        return "white on green"
    if in_red_ez:
        if ch in ("●", "◆", "▼"):
            return "bold yellow on red"
        return "white on red"
    if ch in ("●", "◆"):
        return "bold yellow"
    if ch == "▼":
        return "bold cyan"
    if ch in ("│", "╋"):
        return "dim"
    return "dim"


def _phase_shows_scrimmage_downs(phase: Phase | None) -> bool:
    """Kickoff (and similar) are not offensive series — no 1st-down / down & distance on the diagram."""
    if phase is None:
        return True
    return phase not in (Phase.KICKOFF_KICK, Phase.ONSIDE_KICK)


def format_field_visual(state: GameState, *, phase: Phase | None = None) -> Text:
    """
    Green goal line at 0 (left), Red at 100 (right).
    Endzones, 10-yard ticks, midfield, ball (LOS), first-down marker (when in a scrimmage phase).
    Returns Rich Text with team-colored end zones.
    """
    f = state.field
    d = state.downs
    los = f.scrimmage_line
    show_scrimmage_downs = _phase_shows_scrimmage_downs(phase)

    row = ["·"] * _WIDTH
    for i in range(_EZ):
        row[i] = "░"
        row[_WIDTH - 1 - i] = "░"
    for m in range(10, 100, 10):
        c = _yard_to_col(m)
        row[c] = "│"
    mid = _yard_to_col(50)
    if row[mid] == "·":
        row[mid] = "╋"

    los_c = _yard_to_col(los)
    if show_scrimmage_downs:
        fd = first_down_line_yard(f, d)
        fd_c = _yard_to_col(fd)
        if los_c == fd_c:
            row[los_c] = "◆"
        else:
            row[los_c] = "●"
            if row[fd_c] in ("·", "│", "╋"):
                row[fd_c] = "▼"
            else:
                row[fd_c] = "▼"
    else:
        row[los_c] = "●"

    out = Text()
    out.append("Field\n", style="dim bold")
    out.append("Green goal (0) ←", style="bold green")
    out.append("·" * 12 + " midfield " + "·" * 12, style="dim")
    out.append("→ Red goal (100)\n", style="bold red")
    out.append("  ")
    for i, ch in enumerate(row):
        out.append(ch, style=_grass_char_style(i, ch))
    if show_scrimmage_downs:
        fd = first_down_line_yard(f, d)
        caption = (
            f"\n  ● LOS {los} yd   ·   ▼/◆ 1st-down line {fd} yd   ·   {d.down} & {d.to_go}"
        )
    else:
        caption = f"\n  ● Kickoff spot {los} yd   ·   no offensive down/distance (kicking team)"
    out.append(caption, style="dim")
    return out
