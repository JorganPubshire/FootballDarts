"""ASCII field diagram: endzones, yard markers, LOS, first-down line."""

from __future__ import annotations

from rich.text import Text

from dart_football.engine.phases import Phase, is_scrimmage_play_phase
from dart_football.engine.state import DownAndDistance, FieldPosition, GameState

# Layout: [green EZ][_FIELD_YARD_LINES yard glyphs][red EZ]. One character per integer
# yard line from 0 (left goal) through 100 (right goal) on the playing field.
_EZ = 3
_FIELD_YARD_LINES = 101  # yards 0, 1, …, 100
_TOTAL_WIDTH = _EZ + _FIELD_YARD_LINES + _EZ
# Midfield (50): plus sign — simple midfield anchor; bold so it pops vs dim ticks.
_MIDFIELD_MARK = "+"


def first_down_line_yard(field: FieldPosition, downs: DownAndDistance) -> int:
    """Yard line (0–100) where a first down is earned."""
    s = field.scrimmage_line
    g = field.goal_yard
    t = downs.to_go
    if g == 100:
        return min(100, s + t)
    return max(0, s - t)


def _yard_to_col(yard: int) -> int:
    """Map field yard line 0..100 to column index in the full row (including end zones)."""
    y = max(0, min(100, int(round(yard))))
    return _EZ + y


def _append_field_axis_labels(out: Text) -> None:
    """
    One row (total width _TOTAL_WIDTH) aligned with the grass row: yard 0 at first
    field column, yard 50 at midfield, yard 100 at last field column. Preceded by
    two spaces to match the grass row indent.
    """
    w = _TOTAL_WIDTH
    mid_abs = _EZ + 50
    left_full = "Green goal ←"
    mid = "midfield"
    right = "→ Red goal"
    mid_start = mid_abs - len(mid) // 2
    right_start = w - len(right)
    left_max = max(1, mid_start - 1)
    left_use = left_full if len(left_full) <= left_max else left_full[:left_max]

    out.append("  ", style="dim")
    out.append(left_use, style="bold green")
    gap1 = mid_start - len(left_use)
    if gap1 > 0:
        out.append(" " * gap1, style="dim")
    out.append(mid, style="dim")
    mid_end = mid_start + len(mid)
    gap2 = right_start - mid_end
    if gap2 > 0:
        out.append(" " * gap2, style="dim")
    out.append(right, style="bold red")


def _grass_char_style(col: int, ch: str) -> str:
    """Color: Green's end zone left (0), Red's end zone right (100); markers in between."""
    in_green_ez = col < _EZ
    in_red_ez = col >= _EZ + _FIELD_YARD_LINES
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
    if ch == _MIDFIELD_MARK:
        return "bold white"
    y_field = col - _EZ
    if ch == "|" and 0 <= y_field < _FIELD_YARD_LINES:
        if y_field % 10 == 0:
            return "bold white"
        return "dim"
    return "dim"


def format_field_visual(state: GameState, *, phase: Phase | None = None) -> Text:
    """
    Green goal line at 0 (left), Red at 100 (right).
    End zones, then yard ticks: | on 5s (dim) and 10s (bold white), + at 50, · elsewhere,
    ball (LOS), first-down marker (only in scrimmage phases).
    """
    f = state.field
    d = state.downs
    los = f.scrimmage_line
    show_scrimmage_downs = is_scrimmage_play_phase(phase)

    row = ["·"] * _TOTAL_WIDTH
    for i in range(_EZ):
        row[i] = "░"
        row[_TOTAL_WIDTH - 1 - i] = "░"

    for y in range(_FIELD_YARD_LINES):
        col = _EZ + y
        if y == 50:
            row[col] = _MIDFIELD_MARK
        elif y % 10 == 0:
            row[col] = "|"
        elif y % 10 == 5:
            row[col] = "|"
        else:
            row[col] = "·"

    los_c = _yard_to_col(los)
    if show_scrimmage_downs:
        fd = first_down_line_yard(f, d)
        fd_c = _yard_to_col(fd)
        if los_c == fd_c:
            row[los_c] = "◆"
        else:
            row[los_c] = "●"
            row[fd_c] = "▼"
    else:
        row[los_c] = "●"

    out = Text()
    out.append("Field\n", style="dim bold")
    _append_field_axis_labels(out)
    out.append("\n  ", style="dim")
    for i, ch in enumerate(row):
        out.append(ch, style=_grass_char_style(i, ch))
    if show_scrimmage_downs:
        fd = first_down_line_yard(f, d)
        caption = (
            f"\n  ● LOS {los} yd   ·   ▼/◆ 1st-down line {fd} yd   ·   {d.down} & {d.to_go}"
        )
    else:
        caption = f"\n  ● LOS {los} yd   ·   no scrimmage down & distance"
    out.append(caption, style="dim")
    return out
