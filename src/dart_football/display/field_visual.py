"""ASCII field diagram: side view with proportional depth, border, and off-field scrimmage arrows."""

from __future__ import annotations

from rich.text import Text

from dart_football.engine.phases import Phase, is_scrimmage_play_phase
from dart_football.engine.state import DownAndDistance, FieldPosition, GameState

# Side view: horizontal = goal line 0 → goal line 100. Vertical span ≈ field width vs length.
# NFL: 120 yd long (incl. end zones) × 53⅓ yd wide → length:width ≈ 2.25 : 1.
_FIELD_LENGTH_YARDS = 120.0
_FIELD_WIDTH_YARDS = 160.0 / 3.0
_ASPECT_LENGTH_PER_WIDTH = _FIELD_LENGTH_YARDS / _FIELD_WIDTH_YARDS

# [green EZ][_FIELD_YARD_LINES][red EZ] — one column per integer yard 0..100 on the axis.
_EZ = 3
_FIELD_YARD_LINES = 101
_TOTAL_WIDTH = _EZ + _FIELD_YARD_LINES + _EZ
_MIDFIELD_MARK = "+"
# Row count from proportion; cap so the block fits typical terminals. Slightly thinner than
# strict proportion reads better in the CLI (_DEPTH_TRIM_ROWS).
_MIN_DEPTH_ROWS = 10
_MAX_DEPTH_ROWS = 22
_DEPTH_TRIM_ROWS = 4
_raw_depth = min(_MAX_DEPTH_ROWS, max(_MIN_DEPTH_ROWS, round(_TOTAL_WIDTH / _ASPECT_LENGTH_PER_WIDTH)))
_DEPTH_ROWS = max(6, _raw_depth - _DEPTH_TRIM_ROWS)

# Scrimmage: arrows outside the field (not on the grass). ▼/▽ above, ▲/△ below; LOS vs first down.
_ARROW_LOS_ABOVE = "▼"
_ARROW_FIRST_ABOVE = "▽"
_ARROW_LOS_BELOW = "▲"
_ARROW_FIRST_BELOW = "△"


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


def _field_yard_from_col(col: int) -> int | None:
    """Yard index 0..100 for a playing-field column, or None in an end zone."""
    if col < _EZ or col >= _EZ + _FIELD_YARD_LINES:
        return None
    return col - _EZ


def _cell_style(row: int, col: int, ch: str, mid_row: int) -> str:
    """Styles for one cell inside the bordered playing area (not border lines)."""
    in_green_ez = col < _EZ
    in_red_ez = col >= _EZ + _FIELD_YARD_LINES
    if in_green_ez:
        if ch == "●":
            return "bold yellow on green"
        return "white on green"
    if in_red_ez:
        if ch == "●":
            return "bold yellow on red"
        return "white on red"

    y = _field_yard_from_col(col)
    assert y is not None
    if ch == "●":
        return "bold yellow"
    if ch == _MIDFIELD_MARK:
        return "bold white"
    if ch == "|":
        if y == 50:
            return "bold white"
        if y % 10 == 0:
            return "bold white"
        return "dim"
    return "dim"


def _build_inner_cell(col: int, row: int, mid_row: int, los_c: int) -> str:
    """Grass cell: yard lines full height; midfield + only on mid_row; ball on mid_row at LOS."""
    if col < _EZ or col >= _EZ + _FIELD_YARD_LINES:
        return "░"
    y = col - _EZ
    if y == 50:
        ch = _MIDFIELD_MARK if row == mid_row else "|"
    elif y % 10 == 0 or y % 10 == 5:
        ch = "|"
    else:
        ch = "·"
    if col == los_c and row == mid_row:
        return "●"
    return ch


def _append_arrow_row(
    out: Text,
    los_c: int,
    fd_c: int,
    same_column: bool,
    los_glyph: str,
    fd_glyph: str,
) -> None:
    line = [" "] * _TOTAL_WIDTH
    if same_column:
        line[los_c] = los_glyph
    else:
        line[los_c] = los_glyph
        line[fd_c] = fd_glyph
    # Match grass columns: body rows are "  │" + field; pad one space so arrows align with inner cells.
    out.append("   ", style="dim")
    for ch in line:
        if ch == " ":
            out.append(" ", style="dim")
        else:
            out.append(ch, style="bold cyan")
    out.append("\n", style="dim")


def _append_bordered_grid(out: Text, mid_row: int, los_c: int) -> None:
    w = _TOTAL_WIDTH
    out.append("  ", style="dim")
    out.append("┌", style="bold white")
    out.append("─" * w, style="bold white")
    out.append("┐\n", style="bold white")

    for row in range(_DEPTH_ROWS):
        out.append("  ", style="dim")
        out.append("│", style="bold white")
        for col in range(w):
            ch = _build_inner_cell(col, row, mid_row, los_c)
            out.append(ch, style=_cell_style(row, col, ch, mid_row))
        out.append("│", style="bold white")
        if row < _DEPTH_ROWS - 1:
            out.append("\n", style="dim")

    out.append("\n  ", style="dim")
    out.append("└", style="bold white")
    out.append("─" * w, style="bold white")
    out.append("┘", style="bold white")


def format_field_visual(state: GameState, *, phase: Phase | None = None) -> Text:
    """
    Side view: yard axis left–right, field width = multiple rows (proportional depth).
    Bold white box around the field. Yard markers run top–bottom; at midfield, ``+`` only
    on the middle row with ``|`` above and below. Ball on the middle row at LOS always.
    During scrimmage, ``▼``/``▽`` above and ``▲``/``△`` below mark LOS and first down.
    """
    f = state.field
    d = state.downs
    los = f.scrimmage_line
    show_scrimmage = is_scrimmage_play_phase(phase)
    mid_row = _DEPTH_ROWS // 2
    los_c = _yard_to_col(los)
    fd: int | None = None
    fd_c: int | None = None
    arrows_same = False
    if show_scrimmage:
        fd = first_down_line_yard(f, d)
        fd_c = _yard_to_col(fd)
        arrows_same = los_c == fd_c

    out = Text()
    out.append("Field\n", style="dim bold")
    _append_field_axis_labels(out)

    if show_scrimmage and fd_c is not None:
        out.append("\n", style="dim")
        _append_arrow_row(
            out,
            los_c,
            fd_c,
            arrows_same,
            _ARROW_LOS_ABOVE,
            _ARROW_FIRST_ABOVE,
        )

    out.append("\n", style="dim")
    _append_bordered_grid(out, mid_row, los_c)

    if show_scrimmage and fd_c is not None:
        out.append("\n", style="dim")
        _append_arrow_row(
            out,
            los_c,
            fd_c,
            arrows_same,
            _ARROW_LOS_BELOW,
            _ARROW_FIRST_BELOW,
        )

    if show_scrimmage and fd is not None and fd_c is not None:
        la = f"{_ARROW_LOS_ABOVE}/{_ARROW_LOS_BELOW}"
        fa = f"{_ARROW_FIRST_ABOVE}/{_ARROW_FIRST_BELOW}"
        if los_c == fd_c:
            caption = f"\n  {la} LOS & 1st-down {los} yd   ·   {d.down} & {d.to_go}"
        else:
            caption = (
                f"\n  {la} LOS {los} yd   ·   {fa} 1st-down line {fd} yd   ·   {d.down} & {d.to_go}"
            )
    else:
        caption = f"\n  ● LOS {los} yd   ·   no scrimmage down & distance"
    out.append(caption, style="dim")
    return out
