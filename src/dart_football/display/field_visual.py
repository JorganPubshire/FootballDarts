"""ASCII field diagram: single-row (default) or multi-row side view with optional border."""

from __future__ import annotations

from rich.text import Text

from dart_football.engine.phases import Phase, is_scrimmage_play_phase
from dart_football.engine.state import DownAndDistance, FieldPosition, GameState

# Side view (large field): horizontal = goal line 0 → goal line 100; depth ≈ field width vs length.
# NFL: 120 yd long (incl. end zones) × 53⅓ yd wide → length:width ≈ 2.25 : 1.
_FIELD_LENGTH_YARDS = 120.0
_FIELD_WIDTH_YARDS = 160.0 / 3.0
_ASPECT_LENGTH_PER_WIDTH = _FIELD_LENGTH_YARDS / _FIELD_WIDTH_YARDS

# [green EZ][_FIELD_YARD_LINES][red EZ] — one column per integer yard 0..100 on the axis.
_EZ = 3
_FIELD_YARD_LINES = 101
_TOTAL_WIDTH = _EZ + _FIELD_YARD_LINES + _EZ
_MIDFIELD_MARK = "+"
_MIN_DEPTH_ROWS = 10
_MAX_DEPTH_ROWS = 22


def _depth_rows_large() -> int:
    """Row count between sidelines (proportional, capped for terminal size)."""
    raw = min(_MAX_DEPTH_ROWS, max(_MIN_DEPTH_ROWS, round(_TOTAL_WIDTH / _ASPECT_LENGTH_PER_WIDTH)))
    return max(6, raw)


# Scrimmage: arrows outside the grass. LOS: ▽/△ above/below; 1st: ▼/▲ above/below.
_ARROW_LOS_ABOVE = "▽"
_ARROW_FIRST_ABOVE = "▼"
_ARROW_LOS_BELOW = "△"
_ARROW_FIRST_BELOW = "▲"


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
    if col < _EZ or col >= _EZ + _FIELD_YARD_LINES:
        return None
    return col - _EZ


def _single_row_grass_style(col: int, ch: str) -> str:
    """Styles for the compact single-line field."""
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
    if ch == "●":
        return "bold yellow"
    if ch == _MIDFIELD_MARK:
        return "bold white"
    y_field = col - _EZ
    if ch == "|" and 0 <= y_field < _FIELD_YARD_LINES:
        if y_field % 10 == 0:
            return "bold white"
        return "dim"
    return "dim"


def _cell_style_large(row: int, col: int, ch: str, mid_row: int) -> str:
    """Styles for one cell inside the bordered playing area."""
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
    *,
    pad_for_border: bool,
) -> None:
    line = [" "] * _TOTAL_WIDTH
    if same_column:
        line[los_c] = los_glyph
    else:
        line[los_c] = los_glyph
        line[fd_c] = fd_glyph
    # Bordered field: body is "  │" + field — pad one space so arrows align with inner cells.
    indent = "   " if pad_for_border else "  "
    out.append(indent, style="dim")
    for ch in line:
        if ch == " ":
            out.append(" ", style="dim")
        else:
            out.append(ch, style="bold cyan")
    out.append("\n", style="dim")


def _append_bordered_grid(out: Text, mid_row: int, los_c: int, depth_rows: int) -> None:
    w = _TOTAL_WIDTH
    out.append("  ", style="dim")
    out.append("┌", style="bold white")
    out.append("─" * w, style="bold white")
    out.append("┐\n", style="bold white")

    for row in range(depth_rows):
        out.append("  ", style="dim")
        out.append("│", style="bold white")
        for col in range(w):
            ch = _build_inner_cell(col, row, mid_row, los_c)
            out.append(ch, style=_cell_style_large(row, col, ch, mid_row))
        out.append("│", style="bold white")
        if row < depth_rows - 1:
            out.append("\n", style="dim")

    out.append("\n  ", style="dim")
    out.append("└", style="bold white")
    out.append("─" * w, style="bold white")
    out.append("┘", style="bold white")


def _append_caption(
    out: Text,
    *,
    show_scrimmage: bool,
    los: int,
    fd: int | None,
    los_c: int,
    fd_c: int | None,
    downs: DownAndDistance,
) -> None:
    if show_scrimmage and fd is not None and fd_c is not None:
        la = f"{_ARROW_LOS_ABOVE}/{_ARROW_LOS_BELOW}"
        fa = f"{_ARROW_FIRST_ABOVE}/{_ARROW_FIRST_BELOW}"
        if los_c == fd_c:
            caption = f"\n  {la} LOS & 1st-down {los} yd   ·   {downs.down} & {downs.to_go}"
        else:
            caption = f"\n  {la} LOS {los} yd   ·   {fa} 1st-down line {fd} yd   ·   {downs.down} & {downs.to_go}"
    else:
        caption = f"\n  ● LOS {los} yd   ·   no scrimmage down & distance"
    out.append(caption, style="dim")


def _format_field_single(state: GameState, phase: Phase | None) -> Text:
    f = state.field
    d = state.downs
    los = f.scrimmage_line
    show_scrimmage = is_scrimmage_play_phase(phase)
    los_c = _yard_to_col(los)
    fd: int | None = None
    fd_c: int | None = None
    arrows_same = False
    if show_scrimmage:
        fd = first_down_line_yard(f, d)
        fd_c = _yard_to_col(fd)
        arrows_same = los_c == fd_c

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
    row[los_c] = "●"

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
            pad_for_border=False,
        )

    out.append("\n  ", style="dim")
    for i, ch in enumerate(row):
        out.append(ch, style=_single_row_grass_style(i, ch))

    if show_scrimmage and fd_c is not None:
        out.append("\n", style="dim")
        _append_arrow_row(
            out,
            los_c,
            fd_c,
            arrows_same,
            _ARROW_LOS_BELOW,
            _ARROW_FIRST_BELOW,
            pad_for_border=False,
        )

    _append_caption(
        out,
        show_scrimmage=show_scrimmage,
        los=los,
        fd=fd,
        los_c=los_c,
        fd_c=fd_c,
        downs=d,
    )
    return out


def _format_field_large(state: GameState, phase: Phase | None) -> Text:
    depth_rows = _depth_rows_large()
    mid_row = depth_rows // 2
    f = state.field
    d = state.downs
    los = f.scrimmage_line
    show_scrimmage = is_scrimmage_play_phase(phase)
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
            pad_for_border=True,
        )

    out.append("\n", style="dim")
    _append_bordered_grid(out, mid_row, los_c, depth_rows)

    if show_scrimmage and fd_c is not None:
        out.append("\n", style="dim")
        _append_arrow_row(
            out,
            los_c,
            fd_c,
            arrows_same,
            _ARROW_LOS_BELOW,
            _ARROW_FIRST_BELOW,
            pad_for_border=True,
        )

    _append_caption(
        out,
        show_scrimmage=show_scrimmage,
        los=los,
        fd=fd,
        los_c=los_c,
        fd_c=fd_c,
        downs=d,
    )
    return out


def format_field_visual(
    state: GameState, *, phase: Phase | None = None, large_field: bool = False
) -> Text:
    """
    ``large_field=False`` (default): one grass row, arrows above/below when scrimmage.
    ``large_field=True``: multi-row depth from length/width proportion, bold white border.
    """
    if large_field:
        return _format_field_large(state, phase)
    return _format_field_single(state, phase)
