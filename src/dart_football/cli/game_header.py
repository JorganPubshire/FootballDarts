"""Rich panel: scoreboard, phase, possession, timeouts, field visual."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dart_football.display import (
    format_distance_to_goal,
    format_down_distance,
    format_line_of_scrimmage,
    format_possession_summary,
    team_display_name,
)
from dart_football.display.field_visual import format_field_visual
from dart_football.engine.phases import Phase, is_scrimmage_play_phase
from dart_football.engine.session import GameSession
from dart_football.engine.state import GameState

_NON_SCRIMMAGE_STATUS: dict[Phase, str] = {
    Phase.CHOOSE_KICK_OR_RECEIVE: "opening: kick or receive (no scrimmage down)",
    Phase.KICKOFF_KICK: "kickoff sequence (no scrimmage series yet)",
    Phase.KICKOFF_RUN_OR_SPOT: "kickoff sequence (no scrimmage series yet)",
    Phase.KICKOFF_RUN_OUT_DART: "kickoff sequence (no scrimmage series yet)",
    Phase.KICKOFF_RETURN_DART: "kickoff sequence (no scrimmage series yet)",
    Phase.ONSIDE_KICK: "onside kick (no scrimmage series yet)",
    Phase.FIELD_GOAL_OFFENSE_DART: "field goal — kicker's dart (no scrimmage down)",
    Phase.FIELD_GOAL_GREEN_CHOICE: "field goal — real kick or fake (no scrimmage down)",
    Phase.FIELD_GOAL_FAKE_OFFENSE: "field goal fake — offense yardage dart (no scrimmage down)",
    Phase.FIELD_GOAL_DEFENSE: "field goal — defense dart (no scrimmage down)",
    Phase.PUNT_ATTEMPT: "punt attempt (no scrimmage down)",
    Phase.AFTER_TOUCHDOWN_CHOICE: "after touchdown — choose extra point or two-point try (no scrimmage down)",
    Phase.EXTRA_POINT_ATTEMPT: "extra point (no scrimmage down)",
    Phase.TWO_POINT_ATTEMPT: "two point conversion (no scrimmage down)",
    Phase.SAFETY_SEQUENCE: "safety — confirm, then free kick from own yard line",
    Phase.OVERTIME_START: "overtime — coin toss (then kick or receive)",
    Phase.GAME_OVER: "game over",
    Phase.PRE_GAME_COIN_TOSS: "pre-game",
}


def _los_distance_suffix(state: GameState, phase: Phase) -> str:
    if is_scrimmage_play_phase(phase):
        return format_down_distance(state)
    return _NON_SCRIMMAGE_STATUS.get(phase, "no scrimmage down & distance")


def render_game_header(
    console: Console, session: GameSession, state: GameState, phase: Phase
) -> None:
    title = Text("Dart Football", style="bold white on dark_blue")
    pq = session.rules.structure.plays_per_quarter
    play_part = f"  ·  Play {state.clock.plays_in_quarter + 1}/{pq}" if pq > 0 else ""
    q_disp = (
        f"OT{state.overtime_period} · Q{state.clock.quarter}"
        if state.overtime_period > 0
        else f"Q{state.clock.quarter}"
    )
    score = Text(
        f"  Red {state.scores.red}  ·  Green {state.scores.green}  ·  {q_disp}{play_part}",
        style="white",
    )
    tbl = Table.grid(padding=(0, 1))
    tbl.add_column(justify="left")
    tbl.add_row(Text.assemble(title, score))
    tbl.add_row(Text(f"Phase: {phase.value.replace('_', ' ')}", style="dim"))
    if phase is not Phase.PRE_GAME_COIN_TOSS or session.head > 0:
        show_ball_on_field = phase is not Phase.CHOOSE_KICK_OR_RECEIVE
        if show_ball_on_field:
            tbl.add_row(Text(format_possession_summary(state), style="yellow"))
        q = state.clock.quarter
        first_half = q <= 2
        t = state.timeouts
        r_left = t.red_q1_q2 if first_half else t.red_q3_q4
        g_left = t.green_q1_q2 if first_half else t.green_q3_q4
        tbl.add_row(
            Text(
                f"Timeouts remaining: Red {r_left}  ·  Green {g_left}",
                style="dim",
            )
        )
        if show_ball_on_field:
            tbl.add_row(
                Text(
                    f"LOS: {format_line_of_scrimmage(state.offense, state.field)}  ·  "
                    f"{format_distance_to_goal(state.offense, state.field)}  ·  "
                    f"{_los_distance_suffix(state, phase)}",
                    style="white",
                )
            )
            tbl.add_row(format_field_visual(state, phase=phase, large_field=session.large_field))
        else:
            tbl.add_row(
                Text(
                    "Kickoff not started — ball is not on the field yet.",
                    style="dim",
                )
            )
    if state.kickoff_kicker and state.kickoff_receiver:
        ko = "Onside kick: " if phase is Phase.ONSIDE_KICK else "Kickoff: "
        tbl.add_row(
            Text(
                f"{ko}{team_display_name(state.kickoff_kicker)} kicks → "
                f"{team_display_name(state.kickoff_receiver)} receives",
                style="cyan",
            )
        )
    if phase is Phase.SCRIMMAGE_DEFENSE and state.scrimmage_pending_offense_yards is not None:
        tbl.add_row(
            Text(
                f"Pending offense yards (before defense dart): {state.scrimmage_pending_offense_yards}",
                style="magenta",
            )
        )
    if phase is Phase.SCRIMMAGE_STRIP_DART:
        eff = state.scrimmage_pending_offense_eff_segment
        py = state.scrimmage_pending_offense_yards
        tbl.add_row(
            Text(
                f"Strip dart: offense wedge {eff}, pending yards if color matches: {py}",
                style="magenta",
            )
        )
    console.print(Panel(tbl, border_style="blue"))
